#!/usr/bin/env python3
"""
Pensare kanban core — storage-agnostic board logic.

Extracted from kanban-server.py so the SAME logic powers three callers:
  - kanban-server.py   (local http server, LocalBackend store)
  - lib/lambda_handler  (online board, S3Backend store)
  - this module's CLI   (`add` / `update`) invoked by the S3 branch of the
                         kanban-add / kanban-update command markdown

Every function takes a `store` (see lib/storage.py) and uses project-relative
keys under `kanban/`. No filesystem assumptions, so it works over local or S3.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys

# Work both as a package import (lib.kanban_core) and as a direct script / in a
# flat Lambda zip where storage.py sits beside this file.
try:
    from . import storage
except ImportError:  # pragma: no cover - direct-run / Lambda flat layout
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import storage  # type: ignore


DEFAULT_CONFIG = {
    "columns": ["Backlog", "In Progress", "Blocked", "Done"],
    "categories": [],
    "id_prefix": "KB",
    "next_id": 1,
}


# ── Parsing helpers (pure) ───────────────────────────────────────────────────


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

    body = "\n".join(lines[end + 1:]).strip()
    return meta, body


def slug_to_column(slug: str, columns: list[str]) -> str:
    """Map a status slug back to its display column name."""
    for col in columns:
        if col.lower().replace(" ", "-") == slug.lower() or col.lower() == slug.lower():
            return col
    return columns[0] if columns else slug


def column_to_slug(col: str) -> str:
    return col.lower().replace(" ", "-")


# ── Board operations (over a storage backend) ────────────────────────────────


def load_config(store) -> dict:
    try:
        return json.loads(store.read("kanban/config.json"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def load_board(store) -> dict:
    config = load_config(store)
    columns = config.get("columns", DEFAULT_CONFIG["columns"])

    items: list[dict] = []
    for key in store.ls("kanban/items", "*.md"):
        try:
            meta, body = parse_frontmatter(store.read(key))
        except (FileNotFoundError, OSError):
            continue
        if not meta:
            continue
        meta["_body"] = body
        items.append(meta)

    board: dict[str, list] = {col: [] for col in columns}
    for item in items:
        col = slug_to_column(item.get("status", ""), columns)
        board.setdefault(col, []).append(item)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    for col in board:
        board[col].sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))

    return {"config": config, "board": board, "columns": columns, "total": len(items)}


def update_item(store, item_key: str, updates: dict) -> None:
    """Update frontmatter fields and optionally append a note."""
    content = store.read(item_key)
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

    if "note" in updates and updates["note"]:
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

    store.write(item_key, "\n".join(new_fm + body_lines) + "\n")


def regenerate_index(store) -> None:
    """Rebuild kanban/INDEX.md from all item files."""
    config = load_config(store)
    columns = config.get("columns", DEFAULT_CONFIG["columns"])
    project = store.project

    items: list[dict] = []
    for key in store.ls("kanban/items", "*.md"):
        try:
            meta, _ = parse_frontmatter(store.read(key))
            if meta:
                items.append(meta)
        except (FileNotFoundError, OSError):
            continue

    priority_order = {"high": 0, "medium": 1, "low": 2}
    counts: dict[str, int] = {col: 0 for col in columns}
    active: list[dict] = []
    done: list[dict] = []

    for item in items:
        col = slug_to_column(item.get("status", ""), columns)
        counts[col] = counts.get(col, 0) + 1
        if columns and col == columns[-1]:
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

    store.write("kanban/INDEX.md", "\n".join(lines) + "\n")


def add_item(
    store,
    title: str,
    category: str = "",
    priority: str = "medium",
    description: str = "",
) -> str:
    """Create a new item file, bump next_id, regenerate the index. Returns the id."""
    config = load_config(store)
    prefix = config.get("id_prefix", "KB")
    next_id = int(config.get("next_id", 1))
    item_id = f"{prefix}-{next_id:03d}"

    columns = config.get("columns", DEFAULT_CONFIG["columns"])
    status = column_to_slug(columns[0]) if columns else "backlog"
    today = datetime.date.today().isoformat()

    item = (
        "---\n"
        f"id: {item_id}\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        f"category: {category}\n"
        f"priority: {priority}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "---\n\n"
        "## Description\n\n"
        f"{description}\n\n"
        "## Notes\n\n"
        f"- {today}: Created\n"
    )
    store.write(f"kanban/items/{item_id}.md", item)

    config["next_id"] = next_id + 1
    store.write("kanban/config.json", json.dumps(config, indent=2) + "\n")

    regenerate_index(store)
    return item_id


# ── Board HTML (shared by local server and hosted upload) ────────────────────
#
# str.format template: literal braces are doubled ({{ }}); single-brace tokens
# {project} and {secret} are substituted. The fetch calls go through apiUrl(),
# which appends ?project=&k= so the SAME page works for the local server
# (secret empty, query ignored) and the hosted CloudFront+Lambda board.

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
.board{{
  display:flex;gap:14px;padding:18px 20px;
  overflow-x:auto;align-items:flex-start;flex:1;min-height:0
}}
.board::-webkit-scrollbar{{height:6px}}
.board::-webkit-scrollbar-track{{background:#0d1117}}
.board::-webkit-scrollbar-thumb{{background:#21262d;border-radius:3px}}
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
.items{{
  padding:10px;display:flex;flex-direction:column;
  gap:8px;overflow-y:auto;flex:1
}}
.items::-webkit-scrollbar{{width:4px}}
.items::-webkit-scrollbar-track{{background:transparent}}
.items::-webkit-scrollbar-thumb{{background:#21262d;border-radius:2px}}
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
.badge,.tag{{
  font-size:11px;padding:2px 7px;border-radius:10px;
  font-weight:500;line-height:1.5;white-space:nowrap
}}
.p-high{{background:#3d1a1c;color:#f85149;border:1px solid #521b1e}}
.p-medium{{background:#2d2208;color:#e3b341;border:1px solid #433410}}
.p-low{{background:#1c2128;color:#6e7681;border:1px solid #21262d}}
.category{{background:#1c2d3d;color:#58a6ff;border:1px solid #1f3a52}}
.empty{{
  color:#484f58;font-size:12px;text-align:center;
  padding:22px 10px;font-style:italic
}}
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
const PROJECT = "{project}";
const SECRET = "{secret}";
let pollTimer = null;

function apiUrl(path) {{
  const p = [];
  if (PROJECT) p.push("project=" + encodeURIComponent(PROJECT));
  if (SECRET) p.push("k=" + encodeURIComponent(SECRET));
  return p.length ? path + "?" + p.join("&") : path;
}}

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
    const r = await fetch(apiUrl(`/api/items/${{id}}`), {{
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
    const r = await fetch(apiUrl("/api/board"));
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


def render_board_html(project: str, secret: str = "") -> str:
    return HTML.format(project=project, secret=secret)


# ── CLI (used by the S3 branch of kanban-add / kanban-update markdown) ────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kanban_core.py")
    parser.add_argument("--project", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--category", default="")
    p_add.add_argument("--priority", default="medium")
    p_add.add_argument("--description", default="")

    p_up = sub.add_parser("update")
    p_up.add_argument("--id", required=True)
    p_up.add_argument("--status")
    p_up.add_argument("--priority")
    p_up.add_argument("--title")
    p_up.add_argument("--category")
    p_up.add_argument("--note")

    args = parser.parse_args(argv)
    store = storage.get_store(args.project)

    if args.cmd == "add":
        item_id = add_item(
            store,
            title=args.title,
            category=args.category,
            priority=args.priority,
            description=args.description,
        )
        print(item_id)
        return 0

    if args.cmd == "update":
        updates = {
            k: v
            for k, v in {
                "status": args.status,
                "priority": args.priority,
                "title": args.title,
                "category": args.category,
                "note": args.note,
            }.items()
            if v is not None
        }
        item_key = f"kanban/items/{args.id}.md"
        if not store.exists(item_key):
            print(f"item not found: {args.id}", file=sys.stderr)
            return 1
        update_item(store, item_key, updates)
        regenerate_index(store)
        print(f"updated {args.id}")
        return 0

    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
