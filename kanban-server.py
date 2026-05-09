#!/usr/bin/env python3
"""
Pensare Kanban Server — local kanban board web app with drag-and-drop.

Usage:
    python3 kanban-server.py <project-name> [--port PORT]

Reads from: ~/.claude/contexts/{project}/kanban/
Serves:     http://localhost:7331
"""

from __future__ import annotations

import sys
import json
import threading
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import datetime

DEFAULT_PORT = 7331


def expand(p: str) -> Path:
    return Path(p).expanduser().resolve()


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body. No external deps."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break

    if end == -1:
        return {}, content

    meta: dict = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            meta[key.strip()] = val

    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def slug_to_column(slug: str, columns: list[str]) -> str:
    """Map a status slug back to its display column name."""
    for col in columns:
        if col.lower().replace(" ", "-") == slug.lower() or col.lower() == slug.lower():
            return col
    return columns[0] if columns else slug


def load_board(kanban_dir: Path) -> dict:
    config_path = kanban_dir / "config.json"
    items_dir = kanban_dir / "items"

    config = {
        "columns": ["Backlog", "In Progress", "Blocked", "Done"],
        "categories": [],
        "id_prefix": "KB",
        "next_id": 1,
    }
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    columns = config.get("columns", ["Backlog", "In Progress", "Blocked", "Done"])

    items: list[dict] = []
    if items_dir.exists():
        for f in sorted(items_dir.glob("*.md")):
            try:
                meta, body = parse_frontmatter(f.read_text())
            except OSError:
                continue
            if not meta:
                continue
            meta["_body"] = body
            items.append(meta)

    board: dict[str, list] = {col: [] for col in columns}
    for item in items:
        status = item.get("status", "")
        col = slug_to_column(status, columns)
        board.setdefault(col, []).append(item)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    for col in board:
        board[col].sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))

    return {"config": config, "board": board, "columns": columns, "total": len(items)}


def update_item(item_path: Path, updates: dict) -> None:
    """Update frontmatter fields and optionally append a note."""
    content = item_path.read_text()
    lines = content.splitlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError("Missing frontmatter")

    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end == -1:
        raise ValueError("Unclosed frontmatter")

    today = datetime.date.today().isoformat()
    fm_updates = {k: v for k, v in updates.items() if k != "note"}
    fm_updates["updated"] = today

    new_fm = [lines[0]]
    for line in lines[1:end]:
        if ":" in line:
            key = line.partition(":")[0].strip()
            if key in fm_updates:
                new_fm.append(f"{key}: {fm_updates[key]}")
                fm_updates.pop(key)
                continue
        new_fm.append(line)
    new_fm.append(lines[end])

    body_lines = lines[end + 1:]

    if "note" in updates:
        note_line = f"- {today}: {updates['note']}"
        note_idx = -1
        for i, line in enumerate(body_lines):
            if line.strip() == "## Notes":
                note_idx = i
                break
        if note_idx == -1:
            body_lines += ["", "## Notes", "", note_line]
        else:
            body_lines.insert(note_idx + 1, note_line)

    item_path.write_text("\n".join(new_fm + body_lines) + "\n")


def regenerate_index(kanban_dir: Path) -> None:
    """Rebuild INDEX.md from all item files."""
    config_path = kanban_dir / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    columns = config.get("columns", ["Backlog", "In Progress", "Blocked", "Done"])
    project = kanban_dir.parent.name

    items_dir = kanban_dir / "items"
    items: list[dict] = []
    if items_dir.exists():
        for f in sorted(items_dir.glob("*.md")):
            try:
                meta, _ = parse_frontmatter(f.read_text())
                if meta:
                    items.append(meta)
            except OSError:
                continue

    priority_order = {"high": 0, "medium": 1, "low": 2}
    counts: dict[str, int] = {col: 0 for col in columns}
    active: list[dict] = []
    done: list[dict] = []

    for item in items:
        col = slug_to_column(item.get("status", ""), columns)
        counts[col] = counts.get(col, 0) + 1
        if col == columns[-1]:
            done.append(item)
        else:
            active.append(item)

    active.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))
    done.sort(key=lambda x: x.get("updated", ""), reverse=True)

    today = datetime.date.today().isoformat()
    lines = [
        f"# Kanban Board — {project}",
        "",
        f"_Last updated: {today}_",
        "",
        "## Column Summary",
        "",
        "| Column | Count |",
        "|--------|-------|",
    ]
    for col in columns:
        lines.append(f"| {col} | {counts.get(col, 0)} |")

    lines += ["", "## Active Items", ""]
    if active:
        lines += [
            "| ID | Title | Status | Category | Priority |",
            "|----|-------|--------|----------|----------|",
        ]
        for item in active:
            lines.append(
                f"| {item.get('id','—')} | {item.get('title','—')} "
                f"| {item.get('status','—')} | {item.get('category','')} "
                f"| {item.get('priority','—')} |"
            )
    else:
        lines.append("_No active items._")

    lines += ["", "## Recently Completed (last 5)", ""]
    if done:
        lines += [
            "| ID | Title | Category | Updated |",
            "|----|-------|----------|---------|",
        ]
        for item in done[:5]:
            lines.append(
                f"| {item.get('id','—')} | {item.get('title','—')} "
                f"| {item.get('category','')} | {item.get('updated','—')} |"
            )
    else:
        lines.append("_No completed items yet._")

    (kanban_dir / "INDEX.md").write_text("\n".join(lines) + "\n")


# ── HTML / CSS / JS ──────────────────────────────────────────────────────────

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pensare Kanban &mdash; {project}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;display:flex;flex-direction:column}}

/* ── Header ── */
header{{
  display:flex;align-items:center;gap:10px;
  padding:14px 20px;border-bottom:1px solid #21262d;
  background:#161b22;flex-shrink:0
}}
header h1{{font-size:15px;font-weight:600;white-space:nowrap}}
header .project{{color:#58a6ff}}
.item-count{{color:#7d8590;font-size:13px;margin-left:auto;white-space:nowrap}}
.pensare-logo{{
  font-size:11px;letter-spacing:.6px;text-transform:uppercase;
  color:#484f58;padding:2px 8px;border:1px solid #21262d;border-radius:10px
}}

/* ── Board ── */
.board{{
  display:flex;gap:14px;padding:18px 20px;
  overflow-x:auto;align-items:flex-start;flex:1;min-height:0
}}
.board::-webkit-scrollbar{{height:6px}}
.board::-webkit-scrollbar-track{{background:#0d1117}}
.board::-webkit-scrollbar-thumb{{background:#21262d;border-radius:3px}}

/* ── Columns ── */
.column{{
  flex:0 0 270px;background:#161b22;border:1px solid #21262d;
  border-radius:8px;display:flex;flex-direction:column;
  max-height:calc(100vh - 100px)
}}
.col-header{{
  display:flex;align-items:center;gap:8px;
  padding:11px 13px;border-bottom:1px solid #21262d;
  font-size:12px;font-weight:600;color:#7d8590;
  text-transform:uppercase;letter-spacing:.5px;
  position:sticky;top:0;background:#161b22;
  border-radius:8px 8px 0 0;flex-shrink:0
}}
.col-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
.d-backlog{{background:#6e7681}}
.d-in-progress{{background:#388bfd}}
.d-blocked{{background:#f85149}}
.d-done{{background:#3fb950}}
.d-default{{background:#bc8cff}}
.col-count{{
  background:#21262d;color:#6e7681;
  font-size:11px;padding:1px 7px;border-radius:10px;
  margin-left:auto;font-weight:500
}}

/* ── Items list ── */
.items{{
  padding:10px;display:flex;flex-direction:column;
  gap:8px;overflow-y:auto;flex:1
}}
.items::-webkit-scrollbar{{width:4px}}
.items::-webkit-scrollbar-track{{background:transparent}}
.items::-webkit-scrollbar-thumb{{background:#21262d;border-radius:2px}}

/* ── Cards ── */
.card{{
  background:#0d1117;border:1px solid #21262d;border-radius:6px;
  padding:11px 12px;cursor:grab;transition:border-color .12s,opacity .12s
}}
.card:hover{{border-color:#388bfd55}}
.card.dragging{{opacity:0.35;cursor:grabbing}}
.column.drag-over{{border-color:#388bfd;background:#161f2e}}
.card-id{{
  font-size:11px;color:#484f58;
  font-family:ui-monospace,"SF Mono",monospace;margin-bottom:5px
}}
.card-title{{
  font-size:13px;color:#e6edf3;line-height:1.45;margin-bottom:9px;
  word-break:break-word
}}
.card-meta{{display:flex;gap:5px;flex-wrap:wrap;align-items:center}}

/* ── Badges ── */
.badge,.tag{{
  font-size:11px;padding:2px 7px;border-radius:10px;
  font-weight:500;line-height:1.5;white-space:nowrap
}}
.p-high{{background:#3d1a1c;color:#f85149;border:1px solid #521b1e}}
.p-medium{{background:#2d2208;color:#e3b341;border:1px solid #433410}}
.p-low{{background:#1c2128;color:#6e7681;border:1px solid #21262d}}
.category{{background:#1c2d3d;color:#58a6ff;border:1px solid #1f3a52}}

/* ── Empty state ── */
.empty{{
  color:#484f58;font-size:12px;text-align:center;
  padding:22px 10px;font-style:italic
}}

/* ── Status bar ── */
.statusbar{{
  position:fixed;bottom:12px;right:16px;
  background:#161b22;border:1px solid #21262d;
  padding:5px 12px;border-radius:20px;
  font-size:11px;color:#484f58;z-index:10
}}
.statusbar.error{{color:#f85149;border-color:#521b1e}}
</style>
</head>
<body>
<header>
  <span class="pensare-logo">pensare</span>
  <h1>Kanban &mdash; <span class="project">{project}</span></h1>
  <span class="item-count" id="count"></span>
</header>
<div class="board" id="board">
  <div style="color:#484f58;padding:20px;font-size:13px">Loading&hellip;</div>
</div>
<div class="statusbar" id="statusbar">Connecting&hellip;</div>

<script>
const POLL_MS = 30000;
let pollTimer = null;

const PRIORITY_CLASS = {{high:"p-high",medium:"p-medium",low:"p-low"}};
const STATUS_DOT = {{
  "backlog":"d-backlog",
  "in-progress":"d-in-progress",
  "blocked":"d-blocked",
  "done":"d-done"
}};

function dotClass(colName) {{
  const slug = colName.toLowerCase().replace(/\\s+/g,"-");
  return STATUS_DOT[slug] || "d-default";
}}

function badge(priority) {{
  if (!priority) return "";
  const cls = PRIORITY_CLASS[priority] || "p-low";
  return `<span class="badge ${{cls}}">${{priority}}</span>`;
}}

function categoryTag(cat) {{
  if (!cat) return "";
  return `<span class="tag category">${{cat}}</span>`;
}}

function renderCard(item) {{
  return `<div class="card" draggable="true"
    ondragstart="dragStart(event,'${{item.id}}')"
    ondragend="dragEnd(event)">
    <div class="card-id">${{item.id || "—"}}</div>
    <div class="card-title">${{escHtml(item.title || "Untitled")}}</div>
    <div class="card-meta">
      ${{badge(item.priority)}}
      ${{categoryTag(item.category)}}
    </div>
  </div>`;
}}

function escHtml(s) {{
  return String(s)
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}}

function renderBoard(data) {{
  const board = document.getElementById("board");
  const count = document.getElementById("count");
  count.textContent = `${{data.total}} item${{data.total === 1 ? "" : "s"}}`;

  board.innerHTML = data.columns.map(col => {{
    const items = data.board[col] || [];
    const cards = items.length
      ? items.map(renderCard).join("")
      : `<div class="empty">No items</div>`;
    return `<div class="column"
      ondragover="dragOver(event)"
      ondragleave="dragLeave(event)"
      ondrop="drop(event,'${{escHtml(col)}}')">
      <div class="col-header">
        <div class="col-dot ${{dotClass(col)}}"></div>
        ${{escHtml(col)}}
        <span class="col-count">${{items.length}}</span>
      </div>
      <div class="items">${{cards}}</div>
    </div>`;
  }}).join("");
}}

function setStatus(msg, isError) {{
  const el = document.getElementById("statusbar");
  el.textContent = msg;
  el.className = "statusbar" + (isError ? " error" : "");
}}

let draggedId = null;

function dragStart(e, id) {{
  draggedId = id;
  e.dataTransfer.effectAllowed = "move";
  e.currentTarget.classList.add("dragging");
}}

function dragEnd(e) {{
  e.currentTarget.classList.remove("dragging");
}}

function dragOver(e) {{
  e.preventDefault();
  e.currentTarget.classList.add("drag-over");
}}

function dragLeave(e) {{
  if (!e.currentTarget.contains(e.relatedTarget)) {{
    e.currentTarget.classList.remove("drag-over");
  }}
}}

function drop(e, col) {{
  e.preventDefault();
  e.currentTarget.classList.remove("drag-over");
  if (!draggedId) return;
  const slug = col.toLowerCase().replace(/\\s+/g, "-");
  patch(draggedId, {{status: slug}});
  draggedId = null;
}}

async function patch(id, updates) {{
  try {{
    const r = await fetch(`/api/items/${{id}}`, {{
      method: "PATCH",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify(updates)
    }});
    if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
    await fetchBoard();
  }} catch(e) {{
    setStatus(`Error: ${{e.message}}`, true);
  }}
}}

async function fetchBoard() {{
  try {{
    const r = await fetch("/api/board");
    if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
    const data = await r.json();
    renderBoard(data);
    setStatus(`Updated ${{new Date().toLocaleTimeString()}} · refreshes every 30s`);
  }} catch(e) {{
    setStatus(`Error: ${{e.message}}`, true);
  }}
  pollTimer = setTimeout(fetchBoard, POLL_MS);
}}

fetchBoard();
</script>
</body>
</html>
"""


class KanbanHandler(BaseHTTPRequestHandler):
    kanban_dir: Path
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
                data = load_board(self.kanban_dir)
                self.send_json(data)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        elif path in ("/", "/index.html"):
            html = HTML.format(project=self.project)
            self.send_html(html)

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
        item_path = self.kanban_dir / "items" / f"{item_id}.md"

        if not item_path.exists():
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
            update_item(item_path, updates)
            regenerate_index(self.kanban_dir)
            self.send_json({"ok": True})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)


def make_handler(kanban_dir: Path, project: str):
    class Handler(KanbanHandler):
        pass

    Handler.kanban_dir = kanban_dir
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
        print(f"  Run /pensare setup (with kanban enabled) to create one.")
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"Pensare Kanban — {project}")
    print(f"  Board:  {url}")
    print(f"  Source: {kanban_dir}")
    print("  Press Ctrl+C to stop.\n")

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    server = HTTPServer(("localhost", port), make_handler(kanban_dir, project))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
