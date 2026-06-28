#!/usr/bin/env python3
"""
Pensare Kanban Server — local kanban board web app with drag-and-drop.

Usage:
    python3 kanban-server.py <project-name> [--port PORT]

Reads from: ~/.claude/contexts/{project}/kanban/
Serves:     http://localhost:7331

This is a thin local shell. All board logic lives in lib/kanban_core.py and is
shared with the online (Lambda) board, so the local and hosted boards behave
identically.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# lib/ sits beside this file (dev symlink or installed copy).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import kanban_core, storage, lambda_handler  # noqa: E402

DEFAULT_PORT = 7331

# Offline rewrite: turn hosted-Lambda absolute URLs into relative paths (so /doc and
# /api/* resolve to THIS local server) and point highlight.js at the local /assets copy.
_LAMBDA_RE = re.compile(r"https://[a-z0-9-]+\.lambda-url\.[a-z0-9-]+\.on\.aws")
_HLJS_JS = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"
_HLJS_CSS = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css"


def offline_rewrite(s: str) -> str:
    s = _LAMBDA_RE.sub("", s)
    s = s.replace(_HLJS_JS, "/assets/highlight.min.js").replace(_HLJS_CSS, "/assets/hljs.css")
    return s


def expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


class KanbanHandler(BaseHTTPRequestHandler):
    store: storage.LocalBackend
    project: str

    def log_message(self, fmt, *args):
        pass  # quiet

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _qs_key(self):
        q = parse_qs(urlparse(self.path).query)
        key = (q.get("key") or [""])[0]
        if not key.endswith(".md") or ".." in key or key.startswith("/"):
            return None
        return key

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/board":
            try:
                data = json.dumps(kanban_core.load_board(self.store))
                self._send_bytes(offline_rewrite(data).encode(), "application/json")
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        elif path in ("/", "/index.html"):
            self.send_html(offline_rewrite(kanban_core.render_board_html(self.project)))

        elif path == "/doc":
            key = self._qs_key()
            if not key or not self.store.exists(key):
                self.send_response(404); self.end_headers(); return
            title = key.rsplit("/", 1)[-1][:-3].replace("-", " ").title()
            html = lambda_handler._md_to_html(self.store.read(key), title=title, back_href="/")
            self._send_bytes(offline_rewrite(html).encode(), "text/html; charset=utf-8")

        elif path == "/api/flashcards":
            key = self._qs_key()
            if not key or not self.store.exists(key):
                self.send_json({"error": "not found"}, status=404); return
            self.send_json({"key": key, "cards": lambda_handler._parse_flashcards(self.store.read(key))})

        elif path == "/api/decks":
            self.send_json({"decks": lambda_handler._deck_list(self.store)})

        elif path == "/api/viz":
            key = self._qs_key()
            if not key or not self.store.exists(key):
                self.send_json({"error": "not found"}, status=404); return
            self.send_json({"key": key, "vizzes": lambda_handler._extract_vizzes(self.store.read(key))})

        elif path.startswith("/assets/"):
            name = os.path.basename(path)
            f = (self.store.root / "assets" / name)
            if not f.exists():
                self.send_response(404); self.end_headers(); return
            ctype = "text/javascript" if name.endswith(".js") else "text/css"
            self._send_bytes(f.read_bytes(), ctype)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # One-click sync (used by the in-board Sync buttons; needs internet).
        if urlparse(self.path).path == "/api/sync":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or "{}")
            except json.JSONDecodeError:
                self.send_json({"ok": False, "out": "bad request"}, 400); return
            action = body.get("action")
            if action not in ("pull", "push"):
                self.send_json({"ok": False, "out": "action must be pull or push"}, 400); return
            repo = os.path.dirname(os.path.abspath(__file__))
            script = os.path.join(repo, "deploy", "sync_offline.py")
            s3 = self.project
            try:
                s3 = json.loads(self.store.read("sources.json")).get("sync_project", s3)
            except Exception:
                pass
            if s3 == self.project and s3.endswith("-offline"):
                s3 = s3[:-len("-offline")]
            cmd = ["python3", script, "--project", s3, "--dir", str(self.store.root), action]
            if action == "push" and body.get("dry"):
                cmd.append("--dry-run")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                self.send_json({"ok": r.returncode == 0, "out": (r.stdout + r.stderr).strip()})
            except Exception as exc:
                self.send_json({"ok": False, "out": f"sync failed (offline?): {exc}"}, 500)
            return
        self.send_response(404); self.end_headers()

    def do_PATCH(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/items/"):
            self.send_response(404)
            self.end_headers()
            return

        item_id = path[len("/api/items/"):]
        item_key = f"kanban/items/{item_id}.md"

        if not self.store.exists(item_key):
            self.send_json({"error": f"Item {item_id} not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            updates = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, status=400)
            return

        try:
            kanban_core.update_item(self.store, item_key, updates)
            kanban_core.regenerate_index(self.store)
            self.send_json({"ok": True})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)


def make_handler(store: storage.LocalBackend, project: str):
    class Handler(KanbanHandler):
        pass

    Handler.store = store
    Handler.project = project
    return Handler


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print("Usage: python3 kanban-server.py <project-name> [--port PORT]")
        sys.exit(1)

    project = args[0]
    port = DEFAULT_PORT

    for i, arg in enumerate(args[1:], start=1):
        if arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                print(f"Invalid port: {args[i + 1]}")
                sys.exit(1)

    kanban_dir = expand(f"~/.claude/contexts/{project}/kanban")
    if not kanban_dir.exists():
        print(f"Error: no kanban board found for project '{project}'")
        print(f"  Expected: {kanban_dir}")
        print("  Run /pensare setup (with kanban enabled) to create one.")
        sys.exit(1)

    store = storage.LocalBackend(project)

    url = f"http://localhost:{port}"
    print(f"Pensare Kanban — {project}")
    print(f"  Board:  {url}")
    print(f"  Source: {kanban_dir}")
    print("  Press Ctrl+C to stop.\n")

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    server = HTTPServer(("localhost", port), make_handler(store, project))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
