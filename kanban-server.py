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
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# lib/ sits beside this file (dev symlink or installed copy).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import kanban_core, storage  # noqa: E402

DEFAULT_PORT = 7331


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

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/board":
            try:
                self.send_json(kanban_core.load_board(self.store))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        elif path in ("/", "/index.html"):
            self.send_html(kanban_core.render_board_html(self.project))

        else:
            self.send_response(404)
            self.end_headers()

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
