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


def _rank_key(item: dict) -> int:
    """Secondary sort key: numeric rank if present, else a large sentinel."""
    try:
        return int(str(item.get("rank", "")).strip())
    except (TypeError, ValueError):
        return 10**9


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
        board[col].sort(key=lambda x: (priority_order.get(x.get("priority", "medium"), 1), _rank_key(x)))

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

    active.sort(key=lambda x: (priority_order.get(x.get("priority", "medium"), 1), _rank_key(x)))
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
    leetcode: str = "",
    doc: str = "",
    rank: str = "",
    flashcards: str = "",
) -> str:
    """Create a new item file, bump next_id, regenerate the index. Returns the id.

    Optional ``leetcode`` / ``doc`` URLs and ``rank`` are stored as frontmatter so
    the board can render them as clickable links (see renderCard in the HTML).
    """
    config = load_config(store)
    prefix = config.get("id_prefix", "KB")
    next_id = int(config.get("next_id", 1))
    item_id = f"{prefix}-{next_id:03d}"

    columns = config.get("columns", DEFAULT_CONFIG["columns"])
    status = column_to_slug(columns[0]) if columns else "backlog"
    today = datetime.date.today().isoformat()

    extra = ""
    if rank:
        extra += f"rank: {rank}\n"
    if leetcode:
        extra += f"leetcode: {leetcode}\n"
    if doc:
        extra += f"doc: {doc}\n"
    if flashcards:
        extra += f"flashcards: {flashcards}\n"

    item = (
        "---\n"
        f"id: {item_id}\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        f"category: {category}\n"
        f"priority: {priority}\n"
        f"{extra}"
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
.card-links{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}}
.card-link{{
  font-size:11px;padding:2px 8px;border-radius:6px;text-decoration:none;
  background:#15281c;color:#3fb950;border:1px solid #1f4429
}}
.card-link:hover{{background:#1a3322}}
button.card-link{{font-family:inherit;cursor:pointer}}
.card-link.flashcards{{background:#241a33;color:#bc8cff;border-color:#3a2a52}}
.card-link.flashcards:hover{{background:#2d1f42}}

/* ── Flashcard modal (Reference + Quiz, in-page) ── */
.fc-overlay{{
  position:fixed;inset:0;background:rgba(1,4,9,.72);z-index:100;
  display:none;align-items:center;justify-content:center;padding:20px
}}
.fc-overlay.open{{display:flex}}
.fc-modal{{
  background:#0d1117;border:1px solid #30363d;border-radius:14px;
  width:min(680px,94vw);max-height:88vh;display:flex;flex-direction:column;
  box-shadow:0 18px 60px rgba(0,0,0,.6)
}}
.fc-head{{
  display:flex;align-items:center;gap:10px;padding:13px 16px;
  border-bottom:1px solid #21262d;flex-shrink:0
}}
.fc-title{{font-size:13px;font-weight:600;color:#bc8cff;text-transform:capitalize;white-space:nowrap}}
.fc-modes{{display:flex;gap:4px;background:#161b22;border:1px solid #21262d;border-radius:8px;padding:3px}}
.fc-mode{{
  font:inherit;font-size:11px;cursor:pointer;border:none;background:none;
  color:#7d8590;padding:3px 11px;border-radius:6px
}}
.fc-mode.on{{background:#241a33;color:#bc8cff}}
.fc-close{{
  margin-left:auto;background:none;border:none;color:#7d8590;cursor:pointer;
  font-size:18px;line-height:1;padding:2px 6px;border-radius:6px
}}
.fc-close:hover{{background:#21262d;color:#e6edf3}}
.fc-body{{padding:18px 18px 6px;overflow:auto;flex:1}}
.fc-q{{font-size:15px;font-weight:600;color:#e6edf3;line-height:1.5;margin-bottom:14px}}
.fc-a{{font-size:13.5px;color:#c9d1d9;line-height:1.6;white-space:pre-wrap;word-break:break-word}}
.fc-a.hidden{{display:none}}
.fc-a code{{background:#161b22;padding:.12em .35em;border-radius:4px;font-family:ui-monospace,"SF Mono",monospace;font-size:.92em}}
.fc-a pre{{
  background:#161b22;border:1px solid #21262d;border-radius:8px;
  padding:11px 13px;margin:9px 0;overflow-x:auto;white-space:pre
}}
.fc-a pre code{{background:none;padding:0;font-size:12.5px;line-height:1.55;color:#e6edf3}}
.fc-a a{{color:#58a6ff}}
.fc-prompt{{color:#6e7681;font-style:italic;font-size:12.5px}}
.fc-foot{{
  display:flex;align-items:center;gap:8px;padding:12px 16px;
  border-top:1px solid #21262d;flex-wrap:wrap;flex-shrink:0
}}
.fc-btn{{
  font:inherit;font-size:12.5px;cursor:pointer;background:#1c2230;color:#e6edf3;
  border:1px solid #30363d;border-radius:6px;padding:5px 12px
}}
.fc-btn:hover:not(:disabled){{background:#2a3140}}
.fc-btn:disabled{{opacity:.4;cursor:default}}
.fc-btn.good{{background:#15281c;color:#3fb950;border-color:#1f4429}}
.fc-btn.bad{{background:#3d1a1c;color:#f85149;border-color:#521b1e}}
.fc-btn.primary{{background:#241a33;color:#bc8cff;border-color:#3a2a52}}
.fc-prog{{font-size:12px;color:#7d8590;font-variant-numeric:tabular-nums;margin-left:2px}}
.fc-dots{{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap;max-width:50%}}
.fc-dot{{width:8px;height:8px;border-radius:50%;background:#30363d}}
.fc-dot.on{{background:#bc8cff}}
.fc-dot.known{{background:#3fb950}}
.fc-dot.missed{{background:#f85149}}
.fc-result{{text-align:center;padding:18px 8px}}
.fc-score{{font-size:26px;font-weight:700;color:#bc8cff;margin-bottom:6px}}
.fc-result p{{color:#7d8590;font-size:13px;margin-bottom:14px}}
/* tame the full-bleed algo-viz so it fits inside the modal (specificity beats .av) */
.fc-modal .av{{position:static;left:auto;transform:none;width:auto;margin:14px 0 4px}}
.fc-modal .av-body{{grid-template-columns:1fr}}
.fc-viz-loading{{color:#6e7681;font-style:italic;font-size:12px;margin:10px 0}}
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

/* ── Tabs + Study view ── */
.tabs{{display:flex;gap:4px;margin-left:18px}}
.tab{{font:inherit;font-size:12px;cursor:pointer;background:none;border:1px solid #21262d;color:#7d8590;padding:5px 14px;border-radius:7px}}
.tab:hover{{color:#e6edf3}}
.tab.on{{background:#1c2d3d;color:#58a6ff;border-color:#1f3a52}}
.study{{flex:1;overflow-y:auto;padding:18px 24px 60px;min-height:0}}
.study-tabs{{display:flex;gap:6px;max-width:940px;margin:0 auto 18px;flex-wrap:wrap}}
.study-tab{{font:inherit;font-size:13px;cursor:pointer;background:#161b22;border:1px solid #21262d;color:#7d8590;padding:8px 16px;border-radius:8px;display:flex;align-items:center;gap:8px}}
.study-tab:hover{{color:#e6edf3}}
.study-tab.on{{background:#1c2d3d;color:#58a6ff;border-color:#1f3a52}}
.study-tab .cnt{{font-size:11px;color:#6e7681}}
.study-tab.on .cnt{{color:#79c0ff}}
.study-section{{max-width:940px;margin:0 auto 30px}}
.study-h{{display:flex;align-items:baseline;gap:10px;font-size:13px;font-weight:600;color:#7d8590;text-transform:uppercase;letter-spacing:.5px;margin:6px 2px 12px}}
.study-h .sub{{color:#484f58;font-weight:500;text-transform:none;letter-spacing:0;font-size:12px}}
.topic-group{{margin-bottom:12px;border:1px solid #21262d;border-radius:8px;overflow:hidden}}
.topic-head{{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#161b22;cursor:pointer;user-select:none}}
.topic-head:hover{{background:#1a2029}}
.topic-caret{{color:#6e7681;font-size:10px;width:10px}}
.topic-name{{font-size:13px;font-weight:600;color:#e6edf3}}
.topic-prog{{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:11px;color:#7d8590;font-variant-numeric:tabular-nums}}
.bar{{width:84px;height:5px;border-radius:3px;background:#21262d;overflow:hidden}}
.bar > span{{display:block;height:100%;background:#3fb950;transition:width .2s}}
.prob-rows.collapsed{{display:none}}
.prob-row{{display:flex;align-items:center;gap:11px;padding:8px 14px;border-top:1px solid #12161d}}
.prob-row:hover{{background:#11151c}}
.chk{{width:18px;height:18px;border-radius:5px;border:1.5px solid #30363d;background:#0d1117;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:12px;line-height:1}}
.chk.done{{background:#238636;border-color:#2ea043;color:#fff}}
.chk:hover{{border-color:#58a6ff}}
.prob-title{{font-size:13px;color:#e6edf3}}
.prob-title.done{{color:#6e7681;text-decoration:line-through}}
.prob-links{{margin-left:auto;display:flex;gap:7px;flex-shrink:0}}
.deck-row{{display:flex;align-items:center;gap:12px;padding:10px 14px;border:1px solid #21262d;border-radius:8px;margin-bottom:7px}}
.deck-row:hover{{border-color:#30363d}}
.deck-name{{font-size:13px;font-weight:600;color:#e6edf3;min-width:175px}}
.deck-meta{{font-size:11px;color:#7d8590;display:flex;gap:14px;align-items:center}}
.deck-open{{margin-left:auto;flex-shrink:0}}
.study-empty{{color:#484f58;font-size:12px;font-style:italic;padding:8px 2px}}
</style>
</head>
<body>
<header>
  <span class="pensare-logo">pensare</span>
  <h1><span class="project">{project}</span></h1>
  <div class="tabs">
    <button class="tab on" id="tabKanban" onclick="showTab('kanban')">Kanban</button>
    <button class="tab" id="tabStudy" onclick="showTab('study')">Study</button>
  </div>
  <span class="item-count" id="count"></span>
</header>
<div class="board" id="board">
  <div style="color:#484f58;padding:20px;font-size:13px">Loading&hellip;</div>
</div>
<div class="study" id="studyView" style="display:none"></div>
<div class="statusbar" id="statusbar">Connecting&hellip;</div>

<div class="fc-overlay" id="fcOverlay" onclick="if(event.target===this)fcClose()">
  <div class="fc-modal" role="dialog" aria-modal="true">
    <div class="fc-head">
      <span class="fc-title" id="fcTitle">Flashcards</span>
      <div class="fc-modes">
        <button class="fc-mode on" id="fcModeRef" onclick="fcSetMode('reference')">Reference</button>
        <button class="fc-mode" id="fcModeQuiz" onclick="fcSetMode('quiz')">Quiz</button>
      </div>
      <button class="fc-close" onclick="fcClose()" aria-label="Close">&times;</button>
    </div>
    <div class="fc-body" id="fcBody"></div>
    <div class="fc-foot" id="fcFoot"></div>
  </div>
</div>

<script>
const POLL_MS = 30000;
const PROJECT = "{project}";
const SECRET = "{secret}";
let pollTimer = null;
let lastBoardData = null, currentTab = "kanban", decksData = null, studySub = "problems";
const TOPIC_ORDER = ["Arrays & Hashing","Two Pointers","Sliding Window","Stack","Binary Search",
  "Linked List","Trees","Tries","Heap / Priority Queue","Backtracking","Graphs","Advanced Graphs",
  "1-D Dynamic Programming","2-D Dynamic Programming","Greedy","Intervals","Math & Geometry",
  "Bit Manipulation","Concurrency","Design"];

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

function cardLinks(item) {{
  const links = [];
  if (item.leetcode) links.push(
    `<a class="card-link" href="${{escHtml(item.leetcode)}}" target="_blank" rel="noopener" onclick="event.stopPropagation()">LeetCode ↗</a>`);
  if (item.doc) links.push(
    `<a class="card-link" href="${{escHtml(item.doc)}}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Explanation ↗</a>`);
  if (item.flashcards) {{
    let fkey = "";
    try {{ fkey = new URL(item.flashcards).searchParams.get("key") || ""; }} catch (e) {{}}
    if (!fkey && item.flashcard_topic) fkey = item.flashcard_topic + "/flashcards.md";
    links.push(
      `<button class="card-link flashcards" data-fkey="${{escHtml(fkey)}}" onclick="event.stopPropagation();openFlashcards(this.dataset.fkey)">Flashcards ▤</button>`);
  }}
  return links.length ? `<div class="card-links">${{links.join("")}}</div>` : "";
}}

function renderCard(item) {{
  return `<div class="card" draggable="true"
    ondragstart="dragStart(event,'${{item.id}}')"
    ondragend="dragEnd(event)">
    <div class="card-id">${{item.id || "—"}}${{item.rank ? ` · #${{escHtml(item.rank)}}` : ""}}</div>
    <div class="card-title">${{escHtml(item.title || "Untitled")}}</div>
    <div class="card-meta">
      ${{badge(item.priority)}}
      ${{categoryTag(item.category)}}
    </div>
    ${{cardLinks(item)}}
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
  lastBoardData = data;
  const board = document.getElementById("board");
  const count = document.getElementById("count");
  // Concept items live in the Study › Concepts tab, not on the kanban.
  const isConcept = it => (it.category || "") === "Concept";
  const shownTotal = data.columns.reduce((a, col) => a + (data.board[col] || []).filter(it => !isConcept(it)).length, 0);
  count.textContent = `${{shownTotal}} item${{shownTotal === 1 ? "" : "s"}}`;
  if (currentTab === "study") renderStudy();

  board.innerHTML = data.columns.map(col => {{
    const items = (data.board[col] || []).filter(it => !isConcept(it));
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

// ── Study view: problems grouped by topic + flashcard decks ──
function showTab(tab) {{
  currentTab = tab;
  document.getElementById("tabKanban").classList.toggle("on", tab === "kanban");
  document.getElementById("tabStudy").classList.toggle("on", tab === "study");
  document.getElementById("board").style.display = tab === "kanban" ? "flex" : "none";
  document.getElementById("studyView").style.display = tab === "study" ? "block" : "none";
  if (tab === "study") {{ if (decksData === null) loadDecks(); else renderStudy(); }}
}}

async function loadDecks() {{
  try {{
    const r = await fetch(apiUrl("/api/decks"));
    decksData = (await r.json()).decks || [];
  }} catch (e) {{ decksData = []; }}
  renderStudy();
}}

function isDone(it) {{ return (it.status || "") === "done"; }}

function probRow(it) {{
  const done = isDone(it);
  const links = [];
  if (it.leetcode) links.push(`<a class="card-link" href="${{escHtml(it.leetcode)}}" target="_blank" rel="noopener">LC ↗</a>`);
  if (it.doc) links.push(`<a class="card-link" href="${{escHtml(it.doc)}}" target="_blank" rel="noopener">Doc ↗</a>`);
  return `<div class="prob-row">` +
    `<div class="chk ${{done ? "done" : ""}}" title="toggle done" onclick="toggleDone('${{it.id}}',${{done}})">${{done ? "✓" : ""}}</div>` +
    `<span class="prob-title ${{done ? "done" : ""}}">${{escHtml(it.title || it.id)}}</span>` +
    `<span class="prob-links">${{links.join("")}}</span></div>`;
}}

function conceptRow(it) {{
  const done = isDone(it);
  const link = it.doc
    ? `<a class="card-link" href="${{escHtml(it.doc)}}" target="_blank" rel="noopener">Open lesson ↗</a>`
    : "";
  return `<div class="prob-row">` +
    `<div class="chk ${{done ? "done" : ""}}" title="toggle done" onclick="toggleDone('${{it.id}}',${{done}})">${{done ? "✓" : ""}}</div>` +
    `<span class="prob-title ${{done ? "done" : ""}}">${{escHtml(it.title || it.id)}}</span>` +
    (it.topic ? `<span class="tag category" style="margin-left:8px">${{escHtml(it.topic)}}</span>` : "") +
    `<span class="prob-links">${{link}}</span></div>`;
}}

function deckRow(d) {{
  const pct = parseInt(d.bestScore) || 0;
  const score = d.bestScore ? `best ${{escHtml(d.bestScore)}}` : "not quizzed yet";
  return `<div class="deck-row">` +
    `<span class="deck-name">${{escHtml(d.topic)}}</span>` +
    `<span class="deck-meta"><span>${{d.cards}} cards</span><span>${{score}}</span>` +
    (d.lastQuiz ? `<span>last ${{escHtml(d.lastQuiz)}}</span>` : "") + `</span>` +
    (pct ? `<span class="bar" style="width:70px"><span style="width:${{pct}}%"></span></span>` : "") +
    `<button class="card-link flashcards deck-open" onclick="openFlashcards('${{escHtml(d.key)}}')">▤ Open</button></div>`;
}}

function toggleGroup(el) {{
  el.parentElement.querySelector(".prob-rows").classList.toggle("collapsed");
  const c = el.querySelector(".topic-caret"); if (c) c.textContent = c.textContent === "▾" ? "▸" : "▾";
}}

async function toggleDone(id, currentlyDone) {{
  await patch(id, {{status: currentlyDone ? "backlog" : "done"}});
}}

function showStudySub(sub) {{ studySub = sub; renderStudy(); }}

function renderStudy() {{
  const view = document.getElementById("studyView");
  if (!lastBoardData) {{ view.innerHTML = '<div class="study-empty">Loading…</div>'; return; }}
  const items = [];
  (lastBoardData.columns || []).forEach(col => (lastBoardData.board[col] || []).forEach(it => items.push(it)));
  const isConcept = it => (it.category || "") === "Concept";
  const probs = items.filter(it => it.topic && !isConcept(it));
  const concepts = items.filter(isConcept);
  const probDone = probs.filter(isDone).length;
  const conDone = concepts.filter(isDone).length;
  const shownDecks = decksData ? decksData.filter(d => d.cards > 0 || d.bestScore) : [];
  const totalCards = decksData ? decksData.reduce((a, d) => a + (d.cards || 0), 0) : 0;

  const tab = (id, label, cnt) =>
    `<button class="study-tab ${{studySub === id ? "on" : ""}}" onclick="showStudySub('${{id}}')">` +
    `${{label}} <span class="cnt">${{cnt}}</span></button>`;
  const tabs = `<div class="study-tabs">` +
    tab("problems", "Problems", `${{probDone}} / ${{probs.length}} done`) +
    tab("concepts", "Concepts", `${{conDone}} / ${{concepts.length}} done`) +
    tab("quizzes", "Quizzes", `${{totalCards}} cards · ${{shownDecks.length}} decks`) +
    `</div>`;

  let body;
  if (studySub === "concepts") body = studyConceptsHtml(concepts);
  else if (studySub === "quizzes") body = studyDecksHtml(shownDecks);
  else body = studyProblemsHtml(probs);
  view.innerHTML = tabs + body;
}}

function studyConceptsHtml(concepts) {{
  let html = `<div class="study-section">`;
  if (!concepts.length) return html + '<div class="study-empty">No concept lessons yet.</div></div>';
  const order = TOPIC_ORDER.filter(t => concepts.some(c => c.topic === t))
    .concat([...new Set(concepts.map(c => c.topic))].filter(t => t && !TOPIC_ORDER.includes(t)).sort());
  const sorted = concepts.slice().sort((a, b) =>
    (order.indexOf(a.topic) - order.indexOf(b.topic)) || String(a.id).localeCompare(b.id));
  html += `<div class="topic-group"><div class="prob-rows">` + sorted.map(conceptRow).join("") + `</div></div>`;
  return html + `</div>`;
}}

function studyProblemsHtml(probs) {{
  const groups = {{}};
  probs.forEach(it => {{ (groups[it.topic] = groups[it.topic] || []).push(it); }});
  const order = TOPIC_ORDER.filter(t => groups[t])
    .concat(Object.keys(groups).filter(t => !TOPIC_ORDER.includes(t)).sort());
  let html = `<div class="study-section">`;
  if (!probs.length) html += '<div class="study-empty">No problems tagged yet.</div>';
  order.forEach(topic => {{
    const list = groups[topic].slice().sort((a, b) => (isDone(a) - isDone(b)) || String(a.id).localeCompare(b.id));
    const done = list.filter(isDone).length;
    const pct = list.length ? Math.round(done / list.length * 100) : 0;
    html += `<div class="topic-group"><div class="topic-head" onclick="toggleGroup(this)">` +
      `<span class="topic-caret">▾</span><span class="topic-name">${{escHtml(topic)}}</span>` +
      `<span class="topic-prog">${{done}}/${{list.length}}<span class="bar"><span style="width:${{pct}}%"></span></span></span>` +
      `</div><div class="prob-rows">` + list.map(probRow).join("") + `</div></div>`;
  }});
  return html + `</div>`;
}}

function studyDecksHtml(shown) {{
  let html = `<div class="study-section">`;
  if (!decksData) return html + '<div class="study-empty">Loading decks…</div></div>';
  html += shown.length ? shown.map(deckRow).join("") : '<div class="study-empty">No decks with cards yet.</div>';
  return html + `</div>`;
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

// ── Flashcard modal: Reference (browse Q+A) + Quiz (reveal + self-mark) ──
let fcCards = [], fcIdx = 0, fcMode = "reference", fcRevealed = false;
let fcResults = [], fcDone = false, fcVizCache = {{}};

function fcInline(t) {{
  let s = escHtml(t);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
  // [text](url) markdown links first, so the bare-url pass doesn't swallow them
  s = s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  // bare urls — but not ones already inside an href="…" or anchor text
  s = s.replace(/(^|[^"'>])(https?:\\/\\/[^\\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return s;
}}
function fcMd(src) {{
  // split on ``` fences: odd chunks are code blocks, even chunks inline markdown
  const parts = String(src || "").split("```");
  let html = "";
  for (let i = 0; i < parts.length; i++) {{
    if (i % 2 === 1) {{
      const code = parts[i].replace(/^[a-zA-Z0-9+-]*\\n/, "").replace(/\\n$/, "");
      html += "<pre><code>" + escHtml(code) + "</code></pre>";
    }} else {{
      html += fcInline(parts[i]);
    }}
  }}
  return html;
}}

// If a card answer references a concept doc, mount that doc's live algo-viz
// widget(s) inline below the answer (fetched on demand, cached per deck key).
function fcMountViz(text, container) {{
  const m = String(text).match(/key=(concepts\\/[A-Za-z0-9_.-]+\\.md)/);
  if (!m || !window.renderAlgoViz) return;
  const key = m[1];
  const holder = document.createElement("div");
  holder.className = "fc-viz";
  holder.innerHTML = '<div class="fc-viz-loading">Loading visualization…</div>';
  container.appendChild(holder);
  const mountAll = (vizzes) => {{
    holder.innerHTML = "";
    if (!vizzes || !vizzes.length) {{ holder.remove(); return; }}
    vizzes.forEach(v => {{
      const el = document.createElement("div");
      holder.appendChild(el);
      try {{ window.renderAlgoViz(v, el); }} catch (e) {{ el.remove(); }}
    }});
  }};
  if (fcVizCache[key]) {{ mountAll(fcVizCache[key]); return; }}
  const base = apiUrl("/api/viz");
  fetch(base + (base.includes("?") ? "&" : "?") + "key=" + encodeURIComponent(key))
    .then(r => r.json())
    .then(d => {{ fcVizCache[key] = d.vizzes || []; mountAll(fcVizCache[key]); }})
    .catch(() => holder.remove());
}}

async function openFlashcards(key) {{
  if (!key) return;
  fcCards = []; fcIdx = 0; fcRevealed = false; fcDone = false; fcResults = [];
  document.getElementById("fcTitle").textContent = "Loading…";
  document.getElementById("fcOverlay").classList.add("open");
  document.getElementById("fcBody").innerHTML = '<div class="fc-prompt">Loading deck…</div>';
  document.getElementById("fcFoot").innerHTML = "";
  try {{
    const r = await fetch(apiUrl("/api/flashcards") + (apiUrl("/api/flashcards").includes("?") ? "&" : "?") + "key=" + encodeURIComponent(key));
    if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
    const data = await r.json();
    fcCards = data.cards || [];
    const topic = key.replace(/\\/flashcards\\.md$/, "").replace(/^kb\\//, "").replace(/[-/]/g, " ");
    document.getElementById("fcTitle").textContent = topic || "Flashcards";
    if (!fcCards.length) {{
      document.getElementById("fcBody").innerHTML = '<div class="fc-prompt">This deck has no cards yet.</div>';
      return;
    }}
    fcResults = new Array(fcCards.length).fill(null);
    fcRender();
  }} catch (e) {{
    document.getElementById("fcBody").innerHTML = `<div class="fc-prompt">Couldn't load deck: ${{escHtml(e.message)}}</div>`;
  }}
}}

function fcClose() {{ document.getElementById("fcOverlay").classList.remove("open"); }}

function fcSetMode(mode) {{
  fcMode = mode;
  fcIdx = 0; fcRevealed = false; fcDone = false;
  fcResults = new Array(fcCards.length).fill(null);
  document.getElementById("fcModeRef").classList.toggle("on", mode === "reference");
  document.getElementById("fcModeQuiz").classList.toggle("on", mode === "quiz");
  if (fcCards.length) fcRender();
}}

function fcDots() {{
  return '<div class="fc-dots">' + fcCards.map((c, i) => {{
    let cls = "fc-dot";
    if (fcResults[i] === true) cls += " known";
    else if (fcResults[i] === false) cls += " missed";
    if (i === fcIdx && !fcDone) cls += " on";
    return `<span class="${{cls}}"></span>`;
  }}).join("") + "</div>";
}}

function fcRender() {{
  const body = document.getElementById("fcBody");
  const foot = document.getElementById("fcFoot");
  const card = fcCards[fcIdx];
  const prog = `<span class="fc-prog">${{fcIdx + 1}} / ${{fcCards.length}}</span>`;

  if (fcMode === "quiz" && fcDone) {{
    const known = fcResults.filter(x => x === true).length;
    const missed = fcResults.filter(x => x === false).length;
    const pct = Math.round((known / fcCards.length) * 100);
    body.innerHTML = `<div class="fc-result"><div class="fc-score">${{known}} / ${{fcCards.length}}</div>` +
      `<p>You knew ${{pct}}% of the deck${{missed ? ` · ${{missed}} to review` : " · perfect!"}}</p></div>`;
    foot.innerHTML =
      (missed ? `<button class="fc-btn primary" onclick="fcReviewMissed()">Review ${{missed}} missed</button>` : "") +
      `<button class="fc-btn" onclick="fcRestart()">Restart</button>` +
      `<button class="fc-btn" onclick="fcClose()">Close</button>` + fcDots();
    return;
  }}

  const q = `<div class="fc-q">${{escHtml(card.q)}}</div>`;
  if (fcMode === "reference") {{
    body.innerHTML = q + `<div class="fc-a">${{fcMd(card.a)}}</div>`;
    fcMountViz(card.a, body);
    foot.innerHTML =
      `<button class="fc-btn" onclick="fcGo(-1)" ${{fcIdx === 0 ? "disabled" : ""}}>‹ Prev</button>` +
      `<button class="fc-btn" onclick="fcGo(1)" ${{fcIdx === fcCards.length - 1 ? "disabled" : ""}}>Next ›</button>` +
      prog + fcDots();
  }} else {{
    const a = fcRevealed ? `<div class="fc-a">${{fcMd(card.a)}}</div>`
                         : `<div class="fc-prompt">Press <b>Space</b> or Reveal to show the answer.</div>`;
    body.innerHTML = q + a;
    if (fcRevealed) fcMountViz(card.a, body);
    foot.innerHTML = (fcRevealed
      ? `<button class="fc-btn bad" onclick="fcMark(false)">Review ✗</button>` +
        `<button class="fc-btn good" onclick="fcMark(true)">Got it ✓</button>`
      : `<button class="fc-btn primary" onclick="fcReveal()">Reveal</button>`) +
      prog + fcDots();
  }}
}}

function fcGo(d) {{
  const i = fcIdx + d;
  if (i < 0 || i >= fcCards.length) return;
  fcIdx = i; fcRevealed = false; fcRender();
}}
function fcReveal() {{ fcRevealed = true; fcRender(); }}
function fcMark(known) {{
  fcResults[fcIdx] = known;
  if (fcIdx < fcCards.length - 1) {{ fcIdx++; fcRevealed = false; fcRender(); }}
  else {{ fcDone = true; fcRender(); }}
}}
function fcRestart() {{
  fcIdx = 0; fcRevealed = false; fcDone = false;
  fcResults = new Array(fcCards.length).fill(null);
  fcRender();
}}
function fcReviewMissed() {{
  fcCards = fcCards.filter((c, i) => fcResults[i] === false);
  fcRestart();
}}

document.addEventListener("keydown", (e) => {{
  if (!document.getElementById("fcOverlay").classList.contains("open")) return;
  if (e.key === "Escape") {{ fcClose(); return; }}
  if (!fcCards.length || fcDone) return;
  if (fcMode === "reference") {{
    if (e.key === "ArrowLeft") {{ fcGo(-1); e.preventDefault(); }}
    else if (e.key === "ArrowRight") {{ fcGo(1); e.preventDefault(); }}
  }} else {{
    if (!fcRevealed && (e.key === " " || e.key === "Enter")) {{ fcReveal(); e.preventDefault(); }}
    else if (fcRevealed && e.key === "ArrowRight") {{ fcMark(true); e.preventDefault(); }}
    else if (fcRevealed && e.key === "ArrowLeft") {{ fcMark(false); e.preventDefault(); }}
  }}
}});

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
    p_add.add_argument("--leetcode", default="")
    p_add.add_argument("--doc", default="")
    p_add.add_argument("--rank", default="")
    p_add.add_argument("--flashcards", default="")

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
            leetcode=args.leetcode,
            doc=args.doc,
            rank=args.rank,
            flashcards=args.flashcards,
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
