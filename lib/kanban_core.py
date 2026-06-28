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
    "columns": ["Backlog", "In Progress", "Done"],
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
    # Append any keys that weren't already present (e.g. first time an item gets
    # `companies`), so the UI editor can set fields the file never had.
    for key, val in fm_updates.items():
        new_fm.append(f"{key}: {val}")
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
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:14px 20px;border-bottom:1px solid #21262d;
  background:#161b22;flex-shrink:0
}}
header h1{{font-size:15px;font-weight:600;white-space:nowrap}}
header .project{{color:#58a6ff}}
.item-count{{color:#7d8590;font-size:13px;margin-left:auto;white-space:nowrap}}
.sync-ctl{{display:flex;gap:6px}}
.sync-ctl button{{font:inherit;font-size:12px;cursor:pointer;background:#161b22;border:1px solid #21262d;color:#7d8590;padding:5px 11px;border-radius:7px;white-space:nowrap}}
.sync-ctl button:hover{{color:#e6edf3;border-color:#30363d}}
/* filter bar */
.filterbar{{
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  padding:9px 20px;border-bottom:1px solid #21262d;background:#11151b;flex-shrink:0
}}
.filterbar input,.filterbar select{{
  font:inherit;font-size:12px;background:#0d1117;color:#e6edf3;
  border:1px solid #21262d;border-radius:7px;padding:5px 9px;outline:none
}}
.filterbar input:focus,.filterbar select:focus{{border-color:#1f6feb}}
.filterbar input.search{{min-width:180px}}
.filter-clear{{
  font:inherit;font-size:12px;cursor:pointer;background:none;border:1px solid #21262d;
  color:#7d8590;padding:5px 11px;border-radius:7px
}}
.filter-clear:hover{{color:#e6edf3;border-color:#30363d}}
.filter-count{{color:#6e7681;font-size:12px;margin-left:auto}}
/* editor modal */
.ed-overlay{{
  display:none;position:fixed;inset:0;background:rgba(1,4,9,.72);z-index:50;
  align-items:flex-start;justify-content:center;padding:48px 16px;overflow:auto
}}
.ed-overlay.open{{display:flex}}
.ed-modal{{
  width:100%;max-width:520px;background:#161b22;border:1px solid #30363d;
  border-radius:12px;padding:20px 22px;box-shadow:0 16px 48px rgba(1,4,9,.6)
}}
.ed-head{{display:flex;align-items:center;gap:10px;margin-bottom:16px}}
.ed-head .ed-id{{font-size:12px;color:#6e7681;font-variant-numeric:tabular-nums}}
.ed-head .ed-h{{font-size:15px;font-weight:600}}
.ed-close{{margin-left:auto;background:none;border:none;color:#7d8590;font-size:22px;cursor:pointer;line-height:1}}
.ed-close:hover{{color:#e6edf3}}
.ed-field{{margin-bottom:13px}}
.ed-field label{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#7d8590;margin-bottom:5px}}
.ed-field input,.ed-field select{{
  width:100%;font:inherit;font-size:13px;background:#0d1117;color:#e6edf3;
  border:1px solid #21262d;border-radius:7px;padding:7px 10px;outline:none
}}
.ed-field input:focus,.ed-field select:focus{{border-color:#1f6feb}}
.ed-row{{display:flex;gap:12px}}
.ed-row .ed-field{{flex:1}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;
  background:#0d1117;border:1px solid #21262d;border-radius:7px;padding:6px 8px}}
.chip{{display:inline-flex;align-items:center;gap:5px;background:#2b1d3d;color:#bc8cff;
  border:1px solid #3c2a52;border-radius:10px;font-size:11px;padding:2px 4px 2px 8px}}
.chip button{{background:none;border:none;color:#bc8cff;cursor:pointer;font-size:13px;line-height:1;padding:0 2px}}
.chip button:hover{{color:#fff}}
.chips input{{flex:1;min-width:90px;border:none;background:none;color:#e6edf3;font:inherit;font-size:12px;outline:none;padding:2px}}
.ed-actions{{display:flex;gap:10px;justify-content:flex-end;margin-top:18px}}
.ed-btn{{font:inherit;font-size:13px;cursor:pointer;border-radius:7px;padding:7px 16px;border:1px solid #21262d;background:none;color:#c9d1d9}}
.ed-btn.primary{{background:#238636;border-color:#2ea043;color:#fff;font-weight:500}}
.ed-btn.primary:hover{{background:#2ea043}}
.ed-btn:hover{{border-color:#30363d}}
.card{{cursor:pointer}}
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
  flex:1 1 260px;min-width:240px;background:#161b22;border:1px solid #21262d;
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
.company{{background:#2b1d3d;color:#bc8cff;border:1px solid #3c2a52}}
.technique{{background:#10231c;color:#3fb98a;border:1px solid #1c3d31}}
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
.fc-code{{
  width:100%;min-height:96px;resize:vertical;background:#0d1117;color:#e6edf3;
  border:1px solid #21262d;border-radius:8px;padding:11px 12px;outline:none;
  font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:13px;line-height:1.55;
  tab-size:4;white-space:pre
}}
.fc-code:focus{{border-color:#1f6feb}}
.fc-hint{{color:#6e7681;font-size:11.5px;margin-top:6px}}
.fc-sub{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#7d8590;margin:14px 0 5px}}
.fc-yourcode{{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:10px 12px;overflow:auto}}
.fc-yourcode code{{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12.5px;line-height:1.55;color:#e6edf3;white-space:pre}}
.fc-verdict{{font-size:13px;font-weight:600;padding:7px 11px;border-radius:8px;display:inline-block}}
.fc-verdict.good{{background:#15281c;color:#3fb950;border:1px solid #1f4429}}
.fc-verdict.bad{{background:#3d1a1c;color:#f85149;border:1px solid #521b1e}}
/* full-page typed-code quiz */
.qz-launch{{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.qz-launch-note{{font-size:12px;color:#7d8590}}
.quiz-view{{display:none;position:fixed;inset:0;z-index:60;background:#0d1117;overflow:auto;flex-direction:column}}
.quiz-view.open{{display:flex}}
.quiz-top{{display:flex;align-items:center;gap:12px;padding:14px 22px;border-bottom:1px solid #21262d;background:#161b22;position:sticky;top:0;z-index:1}}
.quiz-top h2{{font-size:15px;font-weight:600}}
.quiz-close{{margin-left:auto;background:none;border:1px solid #21262d;color:#7d8590;border-radius:7px;padding:6px 12px;cursor:pointer;font:inherit;font-size:12px}}
.quiz-close:hover{{color:#e6edf3;border-color:#30363d}}
.quiz-wrap{{max-width:720px;width:100%;margin:0 auto;padding:24px 22px 64px}}
.quiz-lead{{color:#7d8590;font-size:13px;line-height:1.6;margin-bottom:18px}}
.qz-topics{{display:flex;flex-direction:column;gap:7px;margin-bottom:18px}}
.qz-topic{{display:flex;align-items:center;gap:11px;padding:10px 13px;border:1px solid #21262d;border-radius:9px;background:#11151b;cursor:pointer}}
.qz-topic:hover{{border-color:#30363d}}
.qz-topic input{{width:17px;height:17px;accent-color:#bc8cff;cursor:pointer}}
.qz-topic .qz-name{{font-size:13.5px;color:#e6edf3}}
.qz-topic .qz-cnt{{margin-left:auto;font-size:12px;color:#7d8590;font-variant-numeric:tabular-nums}}
.qz-setup-actions{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.qz-selectall{{font:inherit;font-size:12px;cursor:pointer;background:none;border:1px solid #21262d;color:#7d8590;border-radius:7px;padding:7px 13px}}
.qz-selectall:hover{{color:#e6edf3;border-color:#30363d}}
.qz-start{{font:inherit;font-size:13px;font-weight:500;cursor:pointer;background:#238636;border:1px solid #2ea043;color:#fff;border-radius:8px;padding:9px 18px;margin-left:auto}}
.qz-start:hover{{background:#2ea043}}
.qz-start:disabled{{opacity:.4;cursor:default}}
.qz-progress{{height:4px;background:#21262d;border-radius:3px;overflow:hidden;margin-bottom:9px}}
.qz-progress span{{display:block;height:100%;background:#bc8cff;transition:width .2s}}
.qz-count{{font-size:12px;color:#7d8590;margin-bottom:12px;font-variant-numeric:tabular-nums}}
.qz-deck-chip{{display:inline-block;font-size:11px;color:#bc8cff;background:#2b1d3d;border:1px solid #3c2a52;border-radius:10px;padding:1px 9px;margin-bottom:12px}}
.qz-actions{{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}}
.qz-result{{text-align:center;padding:44px 8px}}
/* concept roadmap (DAG view) */
.rm-toggle{{display:flex;gap:6px;margin-bottom:14px}}
.rm-toggle button{{font:inherit;font-size:12px;cursor:pointer;background:#161b22;border:1px solid #21262d;color:#7d8590;padding:6px 16px;border-radius:8px}}
.rm-toggle button.on{{background:#241a33;color:#bc8cff;border-color:#3a2a52}}
.rm-legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:#7d8590;margin-bottom:12px;align-items:center}}
.rm-legend i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}}
.rm-legend .rm-hint{{font-style:italic;color:#6e7681}}
.rm-meta{{font-size:12px;color:#7d8590;font-weight:400}}
/* roadmap graph (SVG DAG) */
.rm-wrap{{overflow-x:auto;border:1px solid #21262d;border-radius:10px;background:#0d1117;padding:10px}}
.rm-gnode:hover rect{{filter:brightness(1.25)}}
/* roadmap node modal */
.rm-modal{{width:100%;max-width:620px;max-height:82vh;display:flex;flex-direction:column;background:#161b22;border:1px solid #30363d;border-radius:12px;box-shadow:0 16px 48px rgba(1,4,9,.6)}}
.rm-modal-head{{display:flex;align-items:center;gap:10px;padding:15px 18px;border-bottom:1px solid #21262d}}
.rm-modal-title{{font-size:15px;font-weight:600;color:#e6edf3}}
.rm-modal-body{{padding:6px 18px 18px;overflow:auto}}
.rm-pre{{font-size:12.5px;color:#8b949e;margin:10px 0 0}}
.rm-note{{font-size:13px;color:#8b949e;line-height:1.55;margin:6px 0}}
.rm-sec{{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#7d8590;margin:14px 0 4px;font-weight:600}}
.rm-skills{{font-size:12px;color:#8b949e;line-height:1.6;margin-top:14px}}
.rm-skills b{{color:#c9d1d9}}
/* per-card move arrows: hidden on desktop (use drag), shown on small screens */
.card-move{{display:none;gap:6px;margin-top:8px}}
.card-move .mv{{flex:1;font:inherit;font-size:14px;line-height:1;cursor:pointer;
  background:#0d1117;border:1px solid #21262d;color:#7d8590;border-radius:6px;padding:7px 0}}
.card-move .mv:disabled{{opacity:.3;cursor:default}}
.card-move .mv:active{{background:#1a2230;color:#e6edf3}}
/* mobile: stack the board vertically, show move arrows, roomier touch targets */
@media (max-width: 700px) {{
  .board{{flex-direction:column;overflow-x:visible;gap:14px;padding:14px}}
  .column{{flex:none;width:100%;min-width:0}}
  .card-move{{display:flex}}
  .card{{cursor:default}}
  .study{{padding:14px 12px 60px}}
  .filterbar{{padding:9px 12px}}
  .filterbar input.search{{min-width:0;flex:1 1 100%}}
  header{{padding:12px 14px}}
  header h1{{font-size:14px}}
}}
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

/* ── Build tab ── */
.build-hero{{margin-bottom:18px}}
.build-title{{font-size:22px;font-weight:700;color:#e6edf3;margin-bottom:6px}}
.build-sub{{font-size:13px;color:#8b949e;line-height:1.6;max-width:760px}}
.build-sub code{{background:#161b22;padding:.1em .4em;border-radius:4px;color:#e3b341;font-size:.92em}}
.build-prog{{display:flex;align-items:center;gap:12px;margin-top:14px;font-size:13px;color:#8b949e}}
.build-prog b{{color:#3fb950;font-size:15px}}
.build-chips{{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin-left:8px}}
.tag.dsa{{background:#1c2d3d;color:#58a6ff;border:1px solid #1f3a52;font-size:10px;padding:2px 7px;border-radius:10px}}
.tag.file-tag{{background:#15281c;color:#3fb950;border:1px solid #1f4429;font-size:10px;padding:2px 7px;border-radius:10px;font-family:ui-monospace,monospace}}
.tag.reuse{{background:#2d2208;color:#e3b341;border:1px solid #433410;font-size:10px;padding:2px 7px;border-radius:10px}}
.lesson-soon{{font-size:11px;color:#484f58;font-style:italic}}
.filetree{{background:#0b0f14;border:1px solid #21262d;border-radius:8px;overflow:hidden;font-family:ui-monospace,"SF Mono",monospace}}
.ft-row{{display:flex;align-items:center;justify-content:space-between;padding:9px 14px;border-top:1px solid #12161d;font-size:12.5px;color:#c9d1d9}}
.ft-head{{background:#161b22;color:#e6edf3;font-weight:600;border-top:none}}
.ft-name{{display:flex;align-items:center;gap:6px}}
.ft-tag{{font-size:10px;color:#6e7681;background:#161b22;padding:2px 8px;border-radius:10px}}
.ft-prog{{font-size:11px;color:#7d8590}}
.ft-row.ready{{background:rgba(63,185,80,.07)}}
.ft-row.ready .ft-name{{color:#3fb950}}
.ft-row.ready .ft-prog{{color:#3fb950}}
</style>
</head>
<body>
<header>
  <span class="pensare-logo">pensare</span>
  <h1><span class="project">{project}</span></h1>
  <div class="tabs">
    <button class="tab on" id="tabKanban" onclick="showTab('kanban')">Kanban</button>
    <button class="tab" id="tabStudy" onclick="showTab('study')">Study</button>
    <button class="tab" id="tabBuild" onclick="showTab('build')">Build</button>
  </div>
  <span class="item-count" id="count"></span>
  <span class="sync-ctl" id="syncCtl"></span>
</header>
<div class="filterbar" id="filterbar">
  <input class="search" id="fltText" type="text" placeholder="Search title / id…" oninput="setFilter('text', this.value)">
  <select id="fltCompany" onchange="setFilter('company', this.value)"><option value="">All companies</option></select>
  <select id="fltTechnique" onchange="setFilter('technique', this.value)"><option value="">All techniques</option></select>
  <select id="fltCategory" onchange="setFilter('category', this.value)"><option value="">All categories</option></select>
  <select id="fltPriority" onchange="setFilter('priority', this.value)">
    <option value="">Any priority</option><option value="high">high</option><option value="medium">medium</option><option value="low">low</option>
  </select>
  <select id="fltStatus" onchange="setFilter('status', this.value)"><option value="">Any status</option></select>
  <button class="filter-clear" onclick="clearFilters()">Clear</button>
  <span class="filter-count" id="fltCount"></span>
</div>
<div class="board" id="board">
  <div style="color:#484f58;padding:20px;font-size:13px">Loading&hellip;</div>
</div>
<div class="study" id="studyView" style="display:none"></div>
<div class="study" id="buildView" style="display:none"></div>
<div class="statusbar" id="statusbar">Connecting&hellip;</div>

<div class="quiz-view" id="quizView"></div>

<div class="ed-overlay" id="rmOverlay" onclick="if(event.target===this)closeRoadmapModal()">
  <div class="rm-modal">
    <div class="rm-modal-head">
      <span class="rm-modal-title" id="rmTitle"></span>
      <button class="ed-close" onclick="closeRoadmapModal()" aria-label="Close">&times;</button>
    </div>
    <div class="rm-modal-body" id="rmBody"></div>
  </div>
</div>

<div class="ed-overlay" id="edOverlay" onclick="if(event.target===this)edClose()">
  <div class="ed-modal" role="dialog" aria-modal="true">
    <div class="ed-head">
      <span class="ed-id" id="edId"></span>
      <span class="ed-h">Edit item</span>
      <button class="ed-close" onclick="edClose()" aria-label="Close">&times;</button>
    </div>
    <div class="ed-field"><label>Title</label><input id="edTitle" type="text"></div>
    <div class="ed-row">
      <div class="ed-field"><label>Status</label><select id="edStatus"></select></div>
      <div class="ed-field"><label>Priority</label>
        <select id="edPriority"><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select>
      </div>
    </div>
    <div class="ed-field"><label>Category</label><select id="edCategory"></select></div>
    <div class="ed-field"><label>Companies / tags</label>
      <div class="chips" id="edChips" onclick="document.getElementById('edChipInput').focus()">
        <input id="edChipInput" type="text" placeholder="add tag + Enter"
          onkeydown="edChipKey(event)">
      </div>
    </div>
    <div class="ed-row">
      <div class="ed-field"><label>LeetCode URL</label><input id="edLeetcode" type="text"></div>
    </div>
    <div class="ed-field"><label>Explanation doc URL</label><input id="edDoc" type="text"></div>
    <div class="ed-actions">
      <button class="ed-btn" onclick="edClose()">Cancel</button>
      <button class="ed-btn primary" onclick="edSave()">Save</button>
    </div>
  </div>
</div>

<div class="fc-overlay" id="fcOverlay" onclick="if(event.target===this)fcClose()">
  <div class="fc-modal" role="dialog" aria-modal="true">
    <div class="fc-head">
      <span class="fc-title" id="fcTitle">Flashcards</span>
      <div class="fc-modes">
        <button class="fc-mode on" id="fcModeRef" onclick="fcSetMode('reference')">Reference</button>
        <button class="fc-mode" id="fcModeQuiz" onclick="fcSetMode('quiz')">Quiz</button>
        <button class="fc-mode" id="fcModeType" onclick="fcSetMode('type')">Type</button>
      </div>
      <button class="fc-close" onclick="fcClose()" aria-label="Close">&times;</button>
    </div>
    <div class="fc-body" id="fcBody"></div>
    <div class="fc-foot" id="fcFoot"></div>
  </div>
</div>

<script>
const POLL_MS = 15000;
const PROJECT = "{project}";
const SECRET = "{secret}";
let pollTimer = null;
let lastBoardData = null, currentTab = "kanban", decksData = null, studySub = "problems";
let conceptView = "list";   // "list" | "roadmap"
// Prerequisite roadmap (DAG) — id, display label/short, board topic for progress,
// topological level (row), prereq edges, why, and the sub-skill breakdown.
const ROADMAP = [
 {{id:"arrays-hashing",label:"Arrays & Hashing",short:"Arrays & Hashing",topic:"Arrays & Hashing",level:1,prereqs:[],note:"Foundational; everything later stores/looks up data with arrays and hash maps.",subskills:["Hash map/set for O(1) lookup & frequency","Prefix sums / running aggregates","Group & dedup with hashing","In-place array tricks","Sorting as preprocessing"]}},
 {{id:"two-pointers",label:"Two Pointers",short:"Two Pointers",topic:"Two Pointers",level:2,prereqs:["arrays-hashing"],note:"Scans sorted/indexed arrays; builds on array traversal.",subskills:["Converging ends (two-sum sorted)","Fast/slow same-direction","In-place partition / dedup","3-pointer combos (3Sum)","Palindrome / trapping-water scans"]}},
 {{id:"stack",label:"Stack",short:"Stack",topic:"Stack",level:2,prereqs:["arrays-hashing"],note:"LIFO use over arrays.",subskills:["Matching pairs / valid parens","Monotonic stack (next greater)","Expression parsing (RPN)","Stack simulation","Min-stack design"]}},
 {{id:"math-geometry",label:"Math & Geometry",short:"Math & Geo",topic:"Math & Geometry",level:2,prereqs:["arrays-hashing"],note:"Mostly self-contained simulation/number theory.",subskills:["Matrix transforms (rotate/spiral)","GCD/LCM, primes, modular","Overflow-safe arithmetic","Geometry basics","Simulation (pow, happy number)"]}},
 {{id:"bit-manipulation",label:"Bit Manipulation",short:"Bit Manip.",topic:"Bit Manipulation",level:2,prereqs:["arrays-hashing"],note:"Low-level toolkit usable early.",subskills:["AND/OR/XOR/NOT & shifts","XOR tricks (single number)","Bit masking & popcount","Get/set/clear i-th bit","Subset enumeration via bitmasks"]}},
 {{id:"binary-search",label:"Binary Search",short:"Binary Search",topic:"Binary Search",level:3,prereqs:["two-pointers"],note:"Converging pointers on sorted data → log search of a space.",subskills:["Lower/upper bound","Rotated / modified arrays","Search on the answer","2D matrix search","Inclusive vs exclusive bounds"]}},
 {{id:"sliding-window",label:"Sliding Window",short:"Sliding Window",topic:"Sliding Window",level:3,prereqs:["two-pointers","arrays-hashing"],note:"Same-direction pointers + a hash map of window contents.",subskills:["Fixed-size window","Variable window grow/shrink","Window + count map","At-most-K / exactly-K trick","Minimum covering window"]}},
 {{id:"linked-list",label:"Linked List",short:"Linked List",topic:"Linked List",level:3,prereqs:["two-pointers"],note:"Fast/slow pointers over node refs.",subskills:["Pointer reversal","Cycle detect / middle (fast-slow)","Dummy-head merge","Nth-from-end / reorder","Deep copy / LRU bookkeeping"]}},
 {{id:"trees",label:"Trees",short:"Trees",topic:"Trees",level:4,prereqs:["linked-list","stack"],note:"Branching linked nodes; traversals need recursion/stack.",subskills:["DFS pre/in/post (rec & iter)","BFS level-order","BST search/insert/validate","Divide & conquer (height/diameter)","LCA & reconstruct, serialize"]}},
 {{id:"tries",label:"Tries",short:"Tries",topic:"Tries",level:5,prereqs:["trees"],note:"Char-keyed n-ary tree.",subskills:["Trie node design","insert / search / startsWith","Wildcard DFS match","Word-search (trie+backtrack)","Prefix aggregation"]}},
 {{id:"heap-priority-queue",label:"Heap / Priority Queue",short:"Heap / PQ",topic:"Heap / Priority Queue",level:5,prereqs:["trees"],note:"Complete binary tree in an array.",subskills:["push/pop, sift, heapify","Top-K / Kth element","Two-heap median","Merge K sorted","Greedy scheduling w/ heap"]}},
 {{id:"backtracking",label:"Backtracking",short:"Backtracking",topic:"Backtracking",level:5,prereqs:["trees"],note:"DFS over an implicit decision tree.",subskills:["Subsets & combinations","Permutations","Constraint search + pruning","Grid / word-search DFS","choose-explore-unchoose"]}},
 {{id:"graphs",label:"Graphs",short:"Graphs",topic:"Graphs",level:6,prereqs:["trees","backtracking","heap-priority-queue"],note:"Trees are acyclic graphs; add a visited set.",subskills:["Adjacency list/matrix","DFS/BFS + visited","Grid-as-graph (islands)","Topological sort","Union-Find","Multi-source BFS / shortest unweighted"]}},
 {{id:"one-d-dp",label:"1-D Dynamic Programming",short:"1-D DP",topic:"1-D Dynamic Programming",level:6,prereqs:["backtracking"],note:"DP = memoized backtracking over overlapping subproblems.",subskills:["Recurrence + base cases","Memo vs tabulation","Linear DP (house robber)","Subsequence DP (LIS, Kadane)","Coin-change / 1-D knapsack","O(1) rolling space"]}},
 {{id:"advanced-graphs",label:"Advanced Graphs",short:"Adv. Graphs",topic:"Advanced Graphs",level:7,prereqs:["graphs"],note:"Weighted edges & global structure.",subskills:["Dijkstra (non-neg weights)","Bellman-Ford / Floyd-Warshall","MST (Prim/Kruskal)","Advanced topo (alien dict)","Eulerian path"]}},
 {{id:"two-d-dp",label:"2-D Dynamic Programming",short:"2-D DP",topic:"2-D Dynamic Programming",level:7,prereqs:["one-d-dp"],note:"1-D recurrences over two dimensions.",subskills:["Grid DP","Two-sequence DP (edit distance/LCS)","0/1 knapsack / target sum","Interval DP","String DP (regex/palindrome)"]}},
 {{id:"greedy",label:"Greedy",short:"Greedy",topic:"Greedy",level:7,prereqs:["one-d-dp"],note:"When local optimum is globally optimal; contrast with DP.",subskills:["Exchange-argument proof","Interval/activity selection","Jump-game reachability","Greedy + heap","Partition-labels grouping"]}},
 {{id:"intervals",label:"Intervals",short:"Intervals",topic:"Intervals",level:8,prereqs:["greedy","sliding-window"],note:"Sort-then-sweep / greedy over ranges.",subskills:["Sort + merge overlapping","Insert interval","Min-removal non-overlap","Meeting rooms (sweep/heap)","Interval intersection"]}}
];
const TOPIC_ORDER = ["Arrays & Hashing","Two Pointers","Sliding Window","Stack","Binary Search",
  "Linked List","Trees","Tries","Heap / Priority Queue","Backtracking","Graphs","Advanced Graphs",
  "1-D Dynamic Programming","2-D Dynamic Programming","Greedy","Intervals","Math & Geometry",
  "Bit Manipulation","Concurrency","Design",
  "Python: Core","Python: Collections","Python: Patterns"];

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

function parseCompanies(raw) {{
  // Frontmatter is parsed naively, so `companies: [A, B]` arrives as a string.
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(s => String(s).trim()).filter(Boolean);
  return String(raw).replace(/^\[|\]$/g, "").split(",").map(s => s.trim()).filter(Boolean);
}}

function companyTags(item) {{
  return parseCompanies(item.companies)
    .map(c => `<span class="tag company">${{escHtml(c)}}</span>`).join("");
}}

function techniqueTags(item) {{
  return parseCompanies(item.techniques)   // same "[a, b]" list format
    .map(t => `<span class="tag technique">${{escHtml(t)}}</span>`).join("");
}}

function colIdx(item) {{
  const cols = (lastBoardData && lastBoardData.columns) || [];
  return cols.findIndex(c => slugify(c) === slugify(item.status || ""));
}}

function cardMove(item) {{
  // Touch-friendly status move (shown only on small screens via CSS); no drag needed.
  const cols = (lastBoardData && lastBoardData.columns) || [];
  const i = colIdx(item);
  const atStart = i <= 0, atEnd = i < 0 || i >= cols.length - 1;
  return `<div class="card-move">` +
    `<button class="mv" title="Move left" onclick="moveCard(event,'${{item.id}}',-1)" ${{atStart ? "disabled" : ""}}>◀</button>` +
    `<button class="mv" title="Move right" onclick="moveCard(event,'${{item.id}}',1)" ${{atEnd ? "disabled" : ""}}>▶</button>` +
    `</div>`;
}}

function renderCard(item) {{
  return `<div class="card" draggable="true"
    ondragstart="dragStart(event,'${{item.id}}')"
    ondragend="dragEnd(event)"
    onclick="openEditor('${{item.id}}')">
    <div class="card-id">${{item.id || "—"}}${{item.rank ? ` · #${{escHtml(item.rank)}}` : ""}}</div>
    <div class="card-title">${{escHtml(item.title || "Untitled")}}</div>
    <div class="card-meta">
      ${{badge(item.priority)}}
      ${{categoryTag(item.category)}}
      ${{companyTags(item)}}
      ${{techniqueTags(item)}}
    </div>
    ${{cardLinks(item)}}
    ${{cardMove(item)}}
  </div>`;
}}

function moveCard(e, id, dir) {{
  e.stopPropagation();                 // don't open the editor
  const cols = (lastBoardData && lastBoardData.columns) || [];
  const found = findItem(id);
  if (!found) return;
  const i = cols.indexOf(found.col);
  const t = i + dir;
  if (t < 0 || t >= cols.length) return;
  patch(id, {{status: slugify(cols[t])}});   // optimistic move + persist
}}

function escHtml(s) {{
  return String(s)
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}}

// Concept / Build items have their own tabs, not the kanban.
const offBoard = it => ["Concept", "Build"].includes(it.category || "");

let filters = {{text:"", company:"", technique:"", category:"", priority:"", status:""}};

function itemMatches(it) {{
  if (filters.company && !parseCompanies(it.companies).includes(filters.company)) return false;
  if (filters.technique && !parseCompanies(it.techniques).includes(filters.technique)) return false;
  if (filters.category && (it.category || "") !== filters.category) return false;
  if (filters.priority && (it.priority || "") !== filters.priority) return false;
  if (filters.status && slugify(it.status || "") !== filters.status) return false;
  if (filters.text) {{
    const hay = `${{it.id || ""}} ${{it.title || ""}}`.toLowerCase();
    if (!hay.includes(filters.text.toLowerCase())) return false;
  }}
  return true;
}}
function slugify(s) {{ return String(s).toLowerCase().replace(/\\s+/g, "-"); }}

function setFilter(key, val) {{ filters[key] = val; if (lastBoardData) renderBoard(lastBoardData); }}
function clearFilters() {{
  filters = {{text:"", company:"", technique:"", category:"", priority:"", status:""}};
  ["fltText","fltCompany","fltTechnique","fltCategory","fltPriority","fltStatus"].forEach(id => {{
    const el = document.getElementById(id); if (el) el.value = "";
  }});
  if (lastBoardData) renderBoard(lastBoardData);
}}

function buildFilterOptions(data) {{
  const all = [];
  data.columns.forEach(col => (data.board[col] || []).forEach(it => {{ if (!offBoard(it)) all.push(it); }}));
  const companies = [...new Set(all.flatMap(it => parseCompanies(it.companies)))].sort();
  const techniques = [...new Set(all.flatMap(it => parseCompanies(it.techniques)))].sort();
  const cats = [...new Set(all.map(it => it.category).filter(Boolean))].sort();
  const fill = (id, vals, keep) => {{
    const el = document.getElementById(id); if (!el) return;
    const cur = el.value;
    el.innerHTML = `<option value="">${{keep}}</option>` +
      vals.map(v => `<option value="${{escHtml(v)}}">${{escHtml(v)}}</option>`).join("");
    el.value = cur;
  }};
  fill("fltCompany", companies, "All companies");
  fill("fltTechnique", techniques, "All techniques");
  fill("fltCategory", cats, "All categories");
  const st = document.getElementById("fltStatus");
  if (st) {{
    const cur = st.value;
    st.innerHTML = `<option value="">Any status</option>` +
      data.columns.map(c => `<option value="${{escHtml(slugify(c))}}">${{escHtml(c)}}</option>`).join("");
    st.value = cur;
  }}
}}

function renderBoard(data) {{
  lastBoardData = data;
  const board = document.getElementById("board");
  const count = document.getElementById("count");
  buildFilterOptions(data);
  const shownTotal = data.columns.reduce((a, col) => a + (data.board[col] || []).filter(it => !offBoard(it)).length, 0);
  count.textContent = `${{shownTotal}} item${{shownTotal === 1 ? "" : "s"}}`;
  if (currentTab === "study") renderStudy();
  else if (currentTab === "build") renderBuild();

  let shownAfter = 0;
  const anyFilter = filters.text || filters.company || filters.category || filters.priority || filters.status;
  board.innerHTML = data.columns.map(col => {{
    const items = (data.board[col] || []).filter(it => !offBoard(it) && itemMatches(it));
    shownAfter += items.length;
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
  const fc = document.getElementById("fltCount");
  if (fc) fc.textContent = anyFilter ? `${{shownAfter}} of ${{shownTotal}} shown` : "";
}}

function setStatus(msg, isError) {{
  const el = document.getElementById("statusbar");
  el.textContent = msg;
  el.className = "statusbar" + (isError ? " error" : "");
}}

// ── Inline card editor ──
function findItem(id) {{
  if (!lastBoardData) return null;
  for (const col of lastBoardData.columns) {{
    const item = (lastBoardData.board[col] || []).find(x => x.id === id);
    if (item) return {{item, col}};
  }}
  return null;
}}

let edItemId = null, edCompanies = [];

function openEditor(id) {{
  const found = findItem(id);
  if (!found) return;
  const it = found.item;
  edItemId = id;
  document.getElementById("edId").textContent = id;
  document.getElementById("edTitle").value = it.title || "";
  document.getElementById("edPriority").value = it.priority || "medium";
  document.getElementById("edLeetcode").value = it.leetcode || "";
  document.getElementById("edDoc").value = it.doc || "";
  const stSel = document.getElementById("edStatus");
  stSel.innerHTML = lastBoardData.columns
    .map(c => `<option value="${{escHtml(slugify(c))}}">${{escHtml(c)}}</option>`).join("");
  stSel.value = slugify(it.status || (lastBoardData.columns[0] || ""));
  const cats = [...new Set(lastBoardData.columns
    .flatMap(c => (lastBoardData.board[c] || []).map(x => x.category).filter(Boolean)))].sort();
  if (it.category && !cats.includes(it.category)) cats.push(it.category);
  const catSel = document.getElementById("edCategory");
  catSel.innerHTML = `<option value="">(none)</option>` +
    cats.map(c => `<option value="${{escHtml(c)}}">${{escHtml(c)}}</option>`).join("");
  catSel.value = it.category || "";
  edCompanies = parseCompanies(it.companies);
  renderChips();
  document.getElementById("edChipInput").value = "";
  document.getElementById("edOverlay").classList.add("open");
}}

function renderChips() {{
  const box = document.getElementById("edChips");
  [...box.querySelectorAll(".chip")].forEach(n => n.remove());
  const input = document.getElementById("edChipInput");
  edCompanies.forEach((c, i) => {{
    const span = document.createElement("span");
    span.className = "chip";
    span.innerHTML = `${{escHtml(c)}} <button onclick="edRemoveChip(${{i}})" aria-label="remove">&times;</button>`;
    box.insertBefore(span, input);
  }});
}}
function edChipKey(e) {{
  if (e.key === "Enter" || e.key === ",") {{
    e.preventDefault();
    const v = e.target.value.trim().replace(/,+$/, "").trim();
    if (v && !edCompanies.includes(v)) {{ edCompanies.push(v); renderChips(); }}
    e.target.value = "";
  }} else if (e.key === "Backspace" && !e.target.value && edCompanies.length) {{
    edCompanies.pop(); renderChips();
  }}
}}
function edRemoveChip(i) {{ edCompanies.splice(i, 1); renderChips(); }}
function edClose() {{ document.getElementById("edOverlay").classList.remove("open"); edItemId = null; }}

function edSave() {{
  if (!edItemId) return;
  const found = findItem(edItemId);
  if (!found) {{ edClose(); return; }}
  const it = found.item;
  const id = edItemId;
  const updates = {{}};
  const title = document.getElementById("edTitle").value.trim();
  const priority = document.getElementById("edPriority").value;
  const category = document.getElementById("edCategory").value;
  const status = document.getElementById("edStatus").value;
  const leetcode = document.getElementById("edLeetcode").value.trim();
  const doc = document.getElementById("edDoc").value.trim();
  if (title !== (it.title || "")) updates.title = `"${{title}}"`;   // quote: titles may contain ':'
  if (priority !== (it.priority || "")) updates.priority = priority;
  if (category !== (it.category || "")) updates.category = category;
  if (status !== slugify(it.status || "")) updates.status = status;
  if (leetcode !== (it.leetcode || "")) updates.leetcode = leetcode;
  if (doc !== (it.doc || "")) updates.doc = doc;
  if (JSON.stringify(edCompanies) !== JSON.stringify(parseCompanies(it.companies)))
    updates.companies = `[${{edCompanies.join(", ")}}]`;
  edClose();
  if (Object.keys(updates).length) patch(id, updates);
}}

document.addEventListener("keydown", (e) => {{
  if (e.key === "Escape" && document.getElementById("edOverlay").classList.contains("open")) edClose();
}});

// ── Study view: problems grouped by topic + flashcard decks ──
function showTab(tab) {{
  currentTab = tab;
  document.getElementById("tabKanban").classList.toggle("on", tab === "kanban");
  document.getElementById("tabStudy").classList.toggle("on", tab === "study");
  document.getElementById("tabBuild").classList.toggle("on", tab === "build");
  document.getElementById("board").style.display = tab === "kanban" ? "flex" : "none";
  document.getElementById("filterbar").style.display = tab === "kanban" ? "flex" : "none";
  document.getElementById("studyView").style.display = tab === "study" ? "block" : "none";
  document.getElementById("buildView").style.display = tab === "build" ? "block" : "none";
  if (tab === "study") {{ if (decksData === null) loadDecks(); else renderStudy(); }}
  if (tab === "build") renderBuild();
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
    companyTags(it) + techniqueTags(it) +
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
  const probs = items.filter(it => it.topic && !["Concept", "Build"].includes(it.category || ""));
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

function setConceptView(v) {{ conceptView = v; renderStudy(); }}

// topic -> {{done,total}} over PROBLEM items (have a topic, not Concept/Build)
function roadmapProgress() {{
  const m = {{}};
  (lastBoardData.columns || []).forEach(col => (lastBoardData.board[col] || []).forEach(it => {{
    if (!it.topic || ["Concept", "Build"].includes(it.category || "")) return;
    (m[it.topic] = m[it.topic] || {{done:0, total:0}}).total++;
    if (isDone(it)) m[it.topic].done++;
  }}));
  return m;
}}

function renderRoadmap() {{
  const prog = roadmapProgress();
  const byId = {{}}; ROADMAP.forEach(n => byId[n.id] = n);
  const P = {{}}, mastered = {{}}, cleared = {{}};
  ROADMAP.forEach(n => {{
    const pr = prog[n.topic] || {{done:0, total:0}};
    P[n.id] = pr.total ? Math.round(pr.done / pr.total * 100) : 0;
    mastered[n.id] = pr.total > 0 && P[n.id] >= 80;
    cleared[n.id] = mastered[n.id] || pr.total === 0;   // no content can't block
  }});
  const stateOf = n => {{
    if (n.prereqs.some(p => byId[p] && !cleared[p])) return "locked";
    if (mastered[n.id]) return "mastered";
    if (P[n.id] > 0) return "in-progress";
    return "available";
  }};
  // layout by topological level
  const levels = {{}};
  ROADMAP.forEach(n => (levels[n.level] = levels[n.level] || []).push(n));
  const W = 960, rowGap = 120, top = 28, nodeW = 152, nodeH = 50;
  const maxLevel = Math.max(...ROADMAP.map(n => n.level));
  const pos = {{}};
  Object.keys(levels).forEach(L => {{
    const arr = levels[L], n = arr.length;
    arr.forEach((nd, i) => {{ pos[nd.id] = {{x: W * (i + 0.5) / n, y: top + (L - 1) * rowGap}}; }});
  }});
  const H = top + (maxLevel - 1) * rowGap + nodeH + 14;
  let edges = "";
  ROADMAP.forEach(n => n.prereqs.forEach(p => {{
    if (!pos[p]) return;
    const a = pos[p], b = pos[n.id], my = (a.y + nodeH + b.y) / 2;
    edges += `<path d="M${{a.x}},${{a.y + nodeH}} C${{a.x}},${{my}} ${{b.x}},${{my}} ${{b.x}},${{b.y}}" fill="none" stroke="#30363d" stroke-width="2"/>`;
  }}));
  const COL = {{locked:["#161b22","#2a2f37","#6e7681"], available:["#11151b","#1f6feb","#c9d1d9"],
               "in-progress":["#2b1d3d","#8957e5","#fff"], mastered:["#0f2417","#2ea043","#fff"]}};
  let nodes = "";
  ROADMAP.forEach(n => {{
    const s = stateOf(n), c = COL[s], pt = pos[n.id], x = pt.x - nodeW / 2, y = pt.y, pct = P[n.id];
    nodes += `<g class="rm-gnode" style="cursor:pointer" onclick="openRoadmapModal('${{n.id}}')">` +
      `<rect x="${{x}}" y="${{y}}" width="${{nodeW}}" height="${{nodeH}}" rx="10" fill="${{c[0]}}" stroke="${{c[1]}}" stroke-width="1.7"/>` +
      `<text x="${{pt.x}}" y="${{y + 21}}" text-anchor="middle" fill="${{c[2]}}" font-size="11.5" font-weight="600">${{escHtml(n.short)}}</text>` +
      `<rect x="${{x + 12}}" y="${{y + 32}}" width="${{nodeW - 24}}" height="6" rx="3" fill="#30363d"/>` +
      (pct > 0 ? `<rect x="${{x + 12}}" y="${{y + 32}}" width="${{(nodeW - 24) * pct / 100}}" height="6" rx="3" fill="#3fb950"/>` : "") +
      `</g>`;
  }});
  const legend = `<div class="rm-legend">` +
    `<span><i style="background:#8957e5"></i>in progress</span>` +
    `<span><i style="background:#2ea043"></i>mastered ≥80%</span>` +
    `<span><i style="background:#1f6feb"></i>available</span>` +
    `<span><i style="background:#2a2f37"></i>locked</span>` +
    `<span class="rm-hint">tap a topic for its lessons & problems</span></div>`;
  return legend + `<div class="rm-wrap"><svg viewBox="0 0 ${{W}} ${{H}}" width="100%" style="min-width:700px;height:auto">${{edges}}${{nodes}}</svg></div>`;
}}

function openRoadmapModal(id) {{
  const n = ROADMAP.find(x => x.id === id); if (!n) return;
  const probs = [], lessons = [];
  (lastBoardData.columns || []).forEach(col => (lastBoardData.board[col] || []).forEach(it => {{
    if (it.topic !== n.topic) return;
    if ((it.category || "") === "Concept") lessons.push(it);
    else if ((it.category || "") !== "Build") probs.push(it);
  }}));
  const done = probs.filter(isDone).length;
  const pre = n.prereqs.map(p => {{ const x = ROADMAP.find(r => r.id === p); return x ? escHtml(x.label) : p; }}).join(", ");
  document.getElementById("rmTitle").innerHTML = `${{escHtml(n.label)}} <span class="rm-meta">${{done}}/${{probs.length}} problems done</span>`;
  document.getElementById("rmBody").innerHTML =
    (pre ? `<p class="rm-pre"><b>Builds on:</b> ${{pre}}</p>` : "") +
    (n.note ? `<p class="rm-note">${{escHtml(n.note)}}</p>` : "") +
    `<div class="rm-sec">Lessons</div>` +
    (lessons.length ? `<div class="prob-rows">` + lessons.map(conceptRow).join("") + `</div>` : `<div class="study-empty">No lesson yet.</div>`) +
    `<div class="rm-sec">Practice problems</div>` +
    (probs.length ? `<div class="prob-rows">` + probs.map(probRow).join("") + `</div>` : `<div class="study-empty">No problems yet.</div>`) +
    `<div class="rm-skills"><b>Key sub-skills:</b> ${{(n.subskills || []).map(escHtml).join(" · ")}}</div>`;
  document.getElementById("rmOverlay").classList.add("open");
}}
function closeRoadmapModal() {{ document.getElementById("rmOverlay").classList.remove("open"); }}

function studyConceptsHtml(concepts) {{
  const toggle = `<div class="rm-toggle">` +
    `<button class="${{conceptView === 'list' ? 'on' : ''}}" onclick="setConceptView('list')">List</button>` +
    `<button class="${{conceptView === 'roadmap' ? 'on' : ''}}" onclick="setConceptView('roadmap')">Roadmap</button></div>`;
  if (conceptView === "roadmap") return `<div class="study-section">` + toggle + renderRoadmap() + `</div>`;
  let html = `<div class="study-section">` + toggle;
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
  html += `<div class="qz-launch">` +
    `<button class="qz-start" style="margin-left:0" onclick="openQuizBuilder()">▤ Build a typed-code quiz →</button>` +
    `<span class="qz-launch-note">Pick topics across decks and type the code answers.</span></div>`;
  html += shown.length ? shown.map(deckRow).join("") : '<div class="study-empty">No decks with cards yet.</div>';
  return html + `</div>`;
}}

// ── Build tab: "Build Your Inference Engine" tracker ──
const BUILD_FILE_ORDER = ["tokenizer.py", "tensor.py", "autograd.py", "attention.py", "sampler.py", "serve.py", "generate.py"];

function buildRow(it) {{
  const done = isDone(it);
  const lesson = it.doc
    ? `<a class="card-link" href="${{escHtml(it.doc)}}" target="_blank" rel="noopener">Open lesson ↗</a>`
    : `<span class="lesson-soon">lesson soon</span>`;
  const chips = `<span class="tag dsa">${{escHtml(it.topic || "")}}</span>` +
    (it.file ? `<span class="tag file-tag">${{escHtml(it.file)}}</span>` : "") +
    (it.related ? `<span class="tag reuse">reuses ${{escHtml(it.related)}}</span>` : "");
  return `<div class="prob-row">` +
    `<div class="chk ${{done ? "done" : ""}}" title="toggle done" onclick="toggleDone('${{it.id}}',${{done}})">${{done ? "✓" : ""}}</div>` +
    `<span class="prob-title ${{done ? "done" : ""}}">${{escHtml(it.title || it.id)}}</span>` +
    `<span class="build-chips">${{chips}}</span>` +
    `<span class="prob-links">${{lesson}}</span></div>`;
}}

function fileTreeHtml(comps) {{
  const byFile = {{}};
  comps.forEach(c => {{ if (c.file) (byFile[c.file] = byFile[c.file] || []).push(c); }});
  let rows = `<div class="ft-row ft-head">tiny-gpt/</div>`;
  rows += `<div class="ft-row"><span class="ft-name">README.md</span><span class="ft-tag">auto-generated</span></div>`;
  rows += `<div class="ft-row"><span class="ft-name">requirements.txt</span><span class="ft-tag">auto-generated</span></div>`;
  rows += `<div class="ft-row"><span class="ft-name">model.py</span><span class="ft-tag">weights provided</span></div>`;
  BUILD_FILE_ORDER.forEach(f => {{
    const list = byFile[f]; if (!list) return;
    const d = list.filter(isDone).length, ready = d === list.length;
    rows += `<div class="ft-row ${{ready ? "ready" : ""}}"><span class="ft-name">${{ready ? "✓ " : ""}}${{escHtml(f)}}</span>` +
      `<span class="ft-prog">${{ready ? "ready" : d + " / " + list.length}}</span></div>`;
  }});
  return `<div class="study-section"><div class="study-h">Your Project <span class="sub">green = your code is ready</span></div>` +
    `<div class="filetree">` + rows + `</div></div>`;
}}

function renderBuild() {{
  const view = document.getElementById("buildView");
  if (!lastBoardData) {{ view.innerHTML = '<div class="study-empty">Loading…</div>'; return; }}
  const items = [];
  (lastBoardData.columns || []).forEach(col => (lastBoardData.board[col] || []).forEach(it => items.push(it)));
  const comps = items.filter(it => (it.category || "") === "Build")
    .sort((a, b) => (parseInt(a.order) || 0) - (parseInt(b.order) || 0));
  const done = comps.filter(isDone).length;
  const pct = comps.length ? Math.round(done / comps.length * 100) : 0;

  let html = `<div class="study-section build-hero">` +
    `<h2 class="build-title">Build Your Inference Engine</h2>` +
    `<p class="build-sub">Every problem you finish is one real component of a tiny GPT. Solve them all and ` +
    `<code>python generate.py "Once upon a"</code> produces text — your code, your repo. Each is a DSA pattern you already know, reframed as the thing it actually powers in an LLM.</p>` +
    `<div class="build-prog"><b>${{done}} / ${{comps.length}}</b> components` +
    `<span class="bar" style="width:220px"><span style="width:${{pct}}%"></span></span></div></div>`;

  const levels = [];
  comps.forEach(c => {{ if (c.level && !levels.includes(c.level)) levels.push(c.level); }});
  html += `<div class="study-section">`;
  levels.forEach(lv => {{
    const list = comps.filter(c => c.level === lv);
    const d = list.filter(isDone).length;
    const p = list.length ? Math.round(d / list.length * 100) : 0;
    html += `<div class="topic-group"><div class="topic-head" onclick="toggleGroup(this)">` +
      `<span class="topic-caret">▾</span><span class="topic-name">${{escHtml(lv)}}</span>` +
      `<span class="topic-prog">${{d}}/${{list.length}}<span class="bar"><span style="width:${{p}}%"></span></span></span>` +
      `</div><div class="prob-rows">` + list.map(buildRow).join("") + `</div></div>`;
  }});
  html += `</div>`;
  html += fileTreeHtml(comps);
  view.innerHTML = html;
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

// Optimistic: apply the change to the in-memory board and re-render immediately,
// then persist in the background. On failure, reconcile from the server.
async function patch(id, updates) {{
  const found = findItem(id);
  if (found) {{
    const it = found.item;
    Object.keys(updates).forEach(k => {{
      if (k === "note") return;
      let v = updates[k];
      if (typeof v === "string") v = v.replace(/^"([\\s\\S]*)"$/, "$1");  // unwrap quoted title
      it[k] = v;
    }});
    if (updates.status) {{
      const target = lastBoardData.columns.find(c => slugify(c) === slugify(updates.status));
      if (target && target !== found.col) {{
        const arr = lastBoardData.board[found.col] || [];
        const i = arr.indexOf(it);
        if (i >= 0) arr.splice(i, 1);
        (lastBoardData.board[target] = lastBoardData.board[target] || []).push(it);
      }}
    }}
    renderBoard(lastBoardData);
  }}
  setStatus("Saving…");
  try {{
    const r = await fetch(apiUrl(`/api/items/${{id}}`), {{
      method: "PATCH",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify(updates)
    }});
    if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
    setStatus(`Saved ${{new Date().toLocaleTimeString()}}`);
  }} catch(e) {{
    setStatus(`Save failed: ${{e.message}} — reverting`, true);
    await fetchBoard();  // reconcile from server
  }}
}}

async function fetchBoard() {{
  clearTimeout(pollTimer);
  try {{
    const r = await fetch(apiUrl("/api/board"));
    if (!r.ok) throw new Error(`HTTP ${{r.status}}`);
    const data = await r.json();
    renderBoard(data);
    setStatus(`Updated ${{new Date().toLocaleTimeString()}} · refreshes every 15s`);
  }} catch(e) {{
    setStatus(`Error: ${{e.message}}`, true);
  }}
  pollTimer = setTimeout(fetchBoard, POLL_MS);
}}

// ── Flashcard modal: Reference (browse Q+A) + Quiz (reveal + self-mark) ──
let fcAllCards = [], fcCards = [], fcIdx = 0, fcMode = "reference", fcRevealed = false;
let fcResults = [], fcDone = false, fcVizCache = {{}};
let fcAutoPass = false, fcLastInput = "";

// Type mode only makes sense for cards whose answer IS code (has a fenced block).
function fcHasCode(c) {{ return /```/.test(String(c.a || "")); }}
function fcCardsForMode(mode) {{
  return mode === "type" ? fcAllCards.filter(fcHasCode) : fcAllCards.slice();
}}

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
    fcAllCards = data.cards || [];
    const topic = key.replace(/\\/flashcards\\.md$/, "").replace(/^kb\\//, "").replace(/[-/]/g, " ");
    document.getElementById("fcTitle").textContent = topic || "Flashcards";
    if (!fcAllCards.length) {{
      document.getElementById("fcBody").innerHTML = '<div class="fc-prompt">This deck has no cards yet.</div>';
      return;
    }}
    fcCards = fcCardsForMode(fcMode);
    fcResults = new Array(fcCards.length).fill(null);
    fcRender();
  }} catch (e) {{
    document.getElementById("fcBody").innerHTML = `<div class="fc-prompt">Couldn't load deck: ${{escHtml(e.message)}}</div>`;
  }}
}}

function fcClose() {{ document.getElementById("fcOverlay").classList.remove("open"); }}

function fcSetMode(mode) {{
  fcMode = mode;
  fcCards = fcCardsForMode(mode);
  fcIdx = 0; fcRevealed = false; fcDone = false; fcLastInput = ""; fcAutoPass = false;
  fcResults = new Array(fcCards.length).fill(null);
  document.getElementById("fcModeRef").classList.toggle("on", mode === "reference");
  document.getElementById("fcModeQuiz").classList.toggle("on", mode === "quiz");
  document.getElementById("fcModeType").classList.toggle("on", mode === "type");
  if (fcAllCards.length) fcRender();
}}

// Pull the code out of an answer (first fenced block), else the whole answer.
function fcExtractCode(a) {{
  const m = String(a || "").match(/```[a-zA-Z0-9+-]*\\n([\\s\\S]*?)```/);
  return (m ? m[1] : String(a || "")).replace(/\\n+$/, "");
}}
// Normalize for comparison: trim each line, collapse internal runs of spaces,
// drop blank lines. Case-sensitive (Python is) and order-sensitive.
function fcNormCode(s) {{
  return String(s).split("\\n").map(l => l.trim().replace(/[ \\t]+/g, " "))
    .filter(l => l.length).join("\\n");
}}
function fcCodeKey(e) {{
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {{ e.preventDefault(); fcCheck(); }}
}}
function fcCheck() {{
  const t = document.getElementById("fcCodeInput");
  fcLastInput = t ? t.value : "";
  fcAutoPass = fcNormCode(fcLastInput) === fcNormCode(fcExtractCode(fcCards[fcIdx].a));
  fcResults[fcIdx] = fcAutoPass;   // tentative — self-grade buttons can override
  fcRevealed = true;
  fcRender();
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
  if (!fcCards.length) {{
    body.innerHTML = `<div class="fc-prompt">${{fcMode === "type"
      ? "No code cards in this deck — Type mode only quizzes cards whose answer is code. Try Reference or Quiz."
      : "No cards to show."}}</div>`;
    foot.innerHTML = `<button class="fc-btn" onclick="fcClose()">Close</button>`;
    return;
  }}
  const card = fcCards[fcIdx];
  const prog = `<span class="fc-prog">${{fcIdx + 1}} / ${{fcCards.length}}</span>`;

  if ((fcMode === "quiz" || fcMode === "type") && fcDone) {{
    const known = fcResults.filter(x => x === true).length;
    const missed = fcResults.filter(x => x === false).length;
    const pct = Math.round((known / fcCards.length) * 100);
    const verb = fcMode === "type" ? "wrote" : "knew";
    body.innerHTML = `<div class="fc-result"><div class="fc-score">${{known}} / ${{fcCards.length}}</div>` +
      `<p>You ${{verb}} ${{pct}}% of the deck${{missed ? ` · ${{missed}} to review` : " · perfect!"}}</p></div>`;
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
  }} else if (fcMode === "type") {{
    if (!fcRevealed) {{
      body.innerHTML = q +
        `<textarea class="fc-code" id="fcCodeInput" spellcheck="false" autocapitalize="off"
           autocorrect="off" placeholder="type the code…" onkeydown="fcCodeKey(event)"></textarea>` +
        `<div class="fc-hint">Press <b>Check</b> or <b>⌘/Ctrl + Enter</b>. Spacing is normalized. If yours is equivalent (e.g. different variable names), mark <b>Got it ✓</b>.</div>`;
      foot.innerHTML = `<button class="fc-btn primary" onclick="fcCheck()">Check</button>` + prog + fcDots();
      setTimeout(() => {{ const t = document.getElementById("fcCodeInput"); if (t) {{ t.value = fcLastInput || ""; t.focus(); }} }}, 0);
    }} else {{
      const verdict = fcAutoPass
        ? `<div class="fc-verdict good">✓ Exact match</div>`
        : `<div class="fc-verdict bad">✗ Not an exact match — compare below</div>`;
      body.innerHTML = q + verdict +
        `<div class="fc-sub">Your answer</div><pre class="fc-yourcode"><code>${{escHtml(fcLastInput || "(empty)")}}</code></pre>` +
        `<div class="fc-sub">Expected</div><div class="fc-a">${{fcMd(card.a)}}</div>`;
      fcMountViz(card.a, body);
      foot.innerHTML =
        `<button class="fc-btn bad" onclick="fcMark(false)">Review ✗</button>` +
        `<button class="fc-btn good" onclick="fcMark(true)">Got it ✓</button>` +
        prog + fcDots();
    }}
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
  if (fcIdx < fcCards.length - 1) {{ fcIdx++; fcRevealed = false; fcLastInput = ""; fcAutoPass = false; fcRender(); }}
  else {{ fcDone = true; fcRender(); }}
}}
function fcRestart() {{
  fcIdx = 0; fcRevealed = false; fcDone = false; fcLastInput = ""; fcAutoPass = false;
  fcResults = new Array(fcCards.length).fill(null);
  fcRender();
}}
function fcReviewMissed() {{
  fcCards = fcCards.filter((c, i) => fcResults[i] === false);
  fcRestart();
}}

// ── Full-page typed-code quiz (Study → Quizzes → Build a quiz) ──
let qzDeckCards = {{}};   // deck key -> [code cards] (cached across opens)
let qzSelected = new Set();
let qzPool = [], qzIdx = 0, qzResults = [], qzRevealed = false, qzAutoPass = false, qzLastInput = "", qzDone = false;

function qzShuffle(a) {{
  for (let i = a.length - 1; i > 0; i--) {{
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }}
  return a;
}}
function qzWrap() {{ return document.querySelector("#quizView .quiz-wrap"); }}

async function openQuizBuilder() {{
  const view = document.getElementById("quizView");
  view.classList.add("open");
  view.innerHTML = `<div class="quiz-top"><h2>Typed-code quiz</h2>` +
    `<button class="quiz-close" onclick="closeQuiz()">Close ✕</button></div>` +
    `<div class="quiz-wrap"><div class="quiz-lead">Loading decks…</div></div>`;
  const decks = (decksData || []).filter(d => d.cards > 0);
  await Promise.all(decks.map(async d => {{
    if (qzDeckCards[d.key]) return;
    try {{
      const r = await fetch(apiUrl("/api/flashcards") + "&key=" + encodeURIComponent(d.key));
      const data = await r.json();
      qzDeckCards[d.key] = (data.cards || []).filter(fcHasCode).map(c => ({{q: c.q, a: c.a, deck: d.topic}}));
    }} catch (e) {{ qzDeckCards[d.key] = []; }}
  }}));
  qzSelected = new Set(decks.filter(d => (qzDeckCards[d.key] || []).length).map(d => d.key));
  renderQuizSetup();
}}

function renderQuizSetup() {{
  const wrap = qzWrap();
  const decks = (decksData || []).filter(d => (qzDeckCards[d.key] || []).length);
  if (!decks.length) {{
    wrap.innerHTML = `<div class="quiz-lead">No decks have code cards yet. Add cards whose answer is a code block (like the Python Syntax deck).</div>`;
    return;
  }}
  const total = decks.filter(d => qzSelected.has(d.key)).reduce((a, d) => a + qzDeckCards[d.key].length, 0);
  wrap.innerHTML =
    `<div class="quiz-lead">Pick the topics to include. You'll type the code answer for each card — spacing is normalized, and you can self-grade equivalent code (e.g. different variable names).</div>` +
    `<div class="qz-topics">` + decks.map(d => {{
      const n = qzDeckCards[d.key].length;
      return `<label class="qz-topic"><input type="checkbox" ${{qzSelected.has(d.key) ? "checked" : ""}} onchange="qzToggle('${{escHtml(d.key)}}')">` +
        `<span class="qz-name">${{escHtml(d.topic)}}</span><span class="qz-cnt">${{n}} card${{n === 1 ? "" : "s"}}</span></label>`;
    }}).join("") + `</div>` +
    `<div class="qz-setup-actions">` +
      `<button class="qz-selectall" onclick="qzSelectAll(true)">Select all</button>` +
      `<button class="qz-selectall" onclick="qzSelectAll(false)">Clear</button>` +
      `<button class="qz-start" ${{total ? "" : "disabled"}} onclick="startQuiz()">Start · ${{total}} question${{total === 1 ? "" : "s"}}</button>` +
    `</div>`;
}}
function qzToggle(key) {{ qzSelected.has(key) ? qzSelected.delete(key) : qzSelected.add(key); renderQuizSetup(); }}
function qzSelectAll(on) {{
  const decks = (decksData || []).filter(d => (qzDeckCards[d.key] || []).length);
  qzSelected = on ? new Set(decks.map(d => d.key)) : new Set();
  renderQuizSetup();
}}

function startQuiz() {{
  qzPool = [];
  (decksData || []).forEach(d => {{ if (qzSelected.has(d.key)) qzPool.push(...(qzDeckCards[d.key] || [])); }});
  qzShuffle(qzPool);
  qzIdx = 0; qzResults = new Array(qzPool.length).fill(null);
  qzRevealed = false; qzAutoPass = false; qzLastInput = ""; qzDone = false;
  qzRender();
}}

function qzRender() {{
  const wrap = qzWrap();
  if (!qzPool.length) {{ qzBackToSetup(); return; }}
  if (qzDone) {{
    const known = qzResults.filter(x => x === true).length;
    const missed = qzResults.filter(x => x === false).length;
    const pct = Math.round(known / qzPool.length * 100);
    wrap.innerHTML = `<div class="qz-result"><div class="fc-score">${{known}} / ${{qzPool.length}}</div>` +
      `<p style="color:#7d8590;margin:6px 0 18px">You wrote ${{pct}}% correct${{missed ? ` · ${{missed}} to review` : " · perfect!"}}</p>` +
      `<div class="qz-actions" style="justify-content:center">` +
        (missed ? `<button class="fc-btn primary" onclick="qzReviewMissed()">Review ${{missed}} missed</button>` : "") +
        `<button class="fc-btn" onclick="startQuiz()">Restart</button>` +
        `<button class="fc-btn" onclick="qzBackToSetup()">New quiz</button>` +
        `<button class="fc-btn" onclick="closeQuiz()">Close</button>` +
      `</div></div>`;
    return;
  }}
  const card = qzPool[qzIdx];
  const prog = `<div class="qz-progress"><span style="width:${{Math.round(qzIdx / qzPool.length * 100)}}%"></span></div>` +
    `<div class="qz-count">${{qzIdx + 1}} / ${{qzPool.length}}</div>`;
  const chip = card.deck ? `<div class="qz-deck-chip">${{escHtml(card.deck)}}</div>` : "";
  if (!qzRevealed) {{
    wrap.innerHTML = prog + chip + `<div class="fc-q">${{escHtml(card.q)}}</div>` +
      `<textarea class="fc-code" id="qzCodeInput" spellcheck="false" autocapitalize="off" autocorrect="off" placeholder="type the code…" onkeydown="qzCodeKey(event)"></textarea>` +
      `<div class="fc-hint">Press <b>Check</b> or <b>⌘/Ctrl + Enter</b>.</div>` +
      `<div class="qz-actions"><button class="fc-btn primary" onclick="qzCheck()">Check</button></div>`;
    const t = document.getElementById("qzCodeInput"); if (t) {{ t.value = qzLastInput || ""; t.focus(); }}
  }} else {{
    const verdict = qzAutoPass
      ? `<div class="fc-verdict good">✓ Exact match</div>`
      : `<div class="fc-verdict bad">✗ Not an exact match — compare below</div>`;
    wrap.innerHTML = prog + chip + `<div class="fc-q">${{escHtml(card.q)}}</div>` + verdict +
      `<div class="fc-sub">Your answer</div><pre class="fc-yourcode"><code>${{escHtml(qzLastInput || "(empty)")}}</code></pre>` +
      `<div class="fc-sub">Expected</div><div class="fc-a">${{fcMd(card.a)}}</div>` +
      `<div class="qz-actions"><button class="fc-btn bad" onclick="qzMark(false)">Review ✗</button>` +
      `<button class="fc-btn good" onclick="qzMark(true)">Got it ✓</button></div>`;
    fcMountViz(card.a, wrap);
  }}
}}
function qzCodeKey(e) {{ if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {{ e.preventDefault(); qzCheck(); }} }}
function qzCheck() {{
  const t = document.getElementById("qzCodeInput");
  qzLastInput = t ? t.value : "";
  qzAutoPass = fcNormCode(qzLastInput) === fcNormCode(fcExtractCode(qzPool[qzIdx].a));
  qzResults[qzIdx] = qzAutoPass;
  qzRevealed = true; qzRender();
}}
function qzMark(known) {{
  qzResults[qzIdx] = known;
  if (qzIdx < qzPool.length - 1) {{ qzIdx++; qzRevealed = false; qzLastInput = ""; qzAutoPass = false; qzRender(); }}
  else {{ qzDone = true; qzRender(); }}
}}
function qzReviewMissed() {{
  qzPool = qzPool.filter((c, i) => qzResults[i] === false);
  qzIdx = 0; qzResults = new Array(qzPool.length).fill(null);
  qzRevealed = false; qzAutoPass = false; qzLastInput = ""; qzDone = false; qzRender();
}}
function qzBackToSetup() {{ renderQuizSetup(); }}
function closeQuiz() {{ document.getElementById("quizView").classList.remove("open"); }}

document.addEventListener("keydown", (e) => {{
  if (!document.getElementById("quizView").classList.contains("open")) return;
  if (e.key === "Escape") {{ closeQuiz(); return; }}
  if (qzDone || !qzPool.length || !qzRevealed) return;
  if (e.key === "ArrowRight") {{ qzMark(true); e.preventDefault(); }}
  else if (e.key === "ArrowLeft") {{ qzMark(false); e.preventDefault(); }}
}});

document.addEventListener("keydown", (e) => {{
  if (!document.getElementById("fcOverlay").classList.contains("open")) return;
  if (e.key === "Escape") {{ fcClose(); return; }}
  if (!fcCards.length || fcDone) return;
  if (fcMode === "reference") {{
    if (e.key === "ArrowLeft") {{ fcGo(-1); e.preventDefault(); }}
    else if (e.key === "ArrowRight") {{ fcGo(1); e.preventDefault(); }}
  }} else if (fcMode === "type") {{
    // While typing (not revealed), let the textarea handle every key; ⌘/Ctrl+Enter
    // (handled on the textarea) checks. After checking, arrows self-grade.
    if (fcRevealed && e.key === "ArrowRight") {{ fcMark(true); e.preventDefault(); }}
    else if (fcRevealed && e.key === "ArrowLeft") {{ fcMark(false); e.preventDefault(); }}
  }} else {{
    if (!fcRevealed && (e.key === " " || e.key === "Enter")) {{ fcReveal(); e.preventDefault(); }}
    else if (fcRevealed && e.key === "ArrowRight") {{ fcMark(true); e.preventDefault(); }}
    else if (fcRevealed && e.key === "ArrowLeft") {{ fcMark(false); e.preventDefault(); }}
  }}
}});

// Sync buttons appear ONLY on the local/offline app (localhost). The hosted board
// can't run the sync script, so they stay hidden there.
function initSync() {{
  if (!/^(localhost|127\\.0\\.0\\.1)$/.test(location.hostname)) return;
  const el = document.getElementById("syncCtl");
  if (!el) return;
  el.innerHTML =
    `<button onclick="runSync('pull')" title="Download the latest from the cloud (needs internet)">↓ Pull</button>` +
    `<button onclick="runSync('push')" title="Upload your offline changes to the cloud (needs internet)">↑ Sync up</button>`;
}}
async function runSync(action) {{
  setStatus(action === "pull" ? "Pulling latest from cloud…" : "Syncing your changes up…");
  try {{
    const r = await fetch("/api/sync", {{method:"POST", headers:{{"Content-Type":"application/json"}},
                                        body: JSON.stringify({{action}})}});
    const d = await r.json();
    const last = (d.out || "").split("\\n").filter(Boolean).slice(-1)[0] || (d.ok ? "done" : "failed");
    setStatus((d.ok ? "✓ " : "✗ ") + last, !d.ok);
    if (action === "pull" && d.ok) fetchBoard();   // show freshly-pulled data
  }} catch (e) {{
    setStatus("Sync failed — are you online? " + e.message, true);
  }}
}}

fetchBoard();
initSync();
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
