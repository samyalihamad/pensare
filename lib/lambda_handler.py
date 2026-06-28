#!/usr/bin/env python3
"""
Pensare online kanban — AWS Lambda handler (Function URL, payload format v2).

One shared Lambda serves every project's board, keyed by an S3 prefix in one
shared bucket. It reuses lib/kanban_core.py over an S3Backend, so the hosted
board behaves identically to the local server.

The Function URL serves BOTH the board HTML and the API from one HTTPS origin,
so the page's relative /api/* fetches work with no CloudFront and no S3 static
hosting to provision.

Routes:
  OPTIONS *                      -> CORS preflight
  GET   /  (or any non-/api)     -> board HTML (project + secret embedded)
  GET   /api/board              -> board JSON
  PATCH /api/items/{id}         -> update item, regenerate index

Auth (private-to-me): every request must carry the project's secret as either
  ?k=<secret>  or  the  X-Board-Secret  header. The secret is compared in
constant time against s3://<bucket>/contexts/<project>/.board-secret.

Environment:
  BUCKET   shared bucket name (required)
  REGION   bucket region (optional; Lambda's region is used otherwise)
"""

from __future__ import annotations

import hmac
import html as _html
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kanban_core  # noqa: E402
import storage  # noqa: E402

BUCKET = os.environ.get("BUCKET", "")
REGION = os.environ.get("REGION") or os.environ.get("AWS_REGION")

# Bundled, dependency-free algo-viz assets (shipped flat in the Lambda zip).
_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_asset(name: str) -> str:
    try:
        with open(os.path.join(_HERE, name), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


ALGO_VIZ_JS = _load_asset("algo_viz.js")
ALGO_VIZ_CSS = _load_asset("algo_viz.css")

# Cache project secrets across warm invocations.
_secret_cache: dict[str, str] = {}

# Cache the parsed board per project across warm invocations. load_board() does
# one S3 GET per item (~90), so without this every poll re-reads the whole board.
# Short TTL so out-of-band edits (CLI / model) still surface within a few seconds;
# UI edits invalidate the entry immediately.
_board_cache: dict[str, dict] = {}
# Short TTL: the cache is per-container, so a PATCH only invalidates the container
# that served it. Keeping the window small bounds cross-container staleness; the
# UI's optimistic updates already make the editor's own changes feel instant.
_BOARD_TTL = 3.0


def _board_payload(store, project: str) -> dict:
    ent = _board_cache.get(project)
    now = time.time()
    if ent and now - ent["ts"] < _BOARD_TTL:
        return ent["data"]
    data = kanban_core.load_board(store)
    _board_cache[project] = {"ts": now, "data": data}
    return data

CORS = {
    "Access-Control-Allow-Origin": "*",  # secret is the real gate; TLS protects it
    "Access-Control-Allow-Methods": "GET,PATCH,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Board-Secret",
    "Access-Control-Max-Age": "86400",
}


def _resp(status: int, body, *, content_type: str = "application/json"):
    headers = dict(CORS)
    headers["Content-Type"] = content_type
    if content_type == "application/json":
        body = json.dumps(body)
    return {"statusCode": status, "headers": headers, "body": body}


def _store_for(project: str):
    return storage.store_for_s3(
        project, bucket=BUCKET, prefix=f"contexts/{project}/", region=REGION
    )


def _expected_secret(project: str) -> str | None:
    if project in _secret_cache:
        return _secret_cache[project]
    try:
        secret = _store_for(project).read(".board-secret").strip()
    except Exception:
        return None
    _secret_cache[project] = secret
    return secret


def _event_bits(event: dict):
    ctx = event.get("requestContext", {}).get("http", {})
    method = ctx.get("method", "GET")
    path = ctx.get("path", "/")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    qs = event.get("queryStringParameters") or {}
    return method, path, headers, qs


# ── Minimal, dependency-free Markdown → HTML (for served explanation docs) ────
#
# Lambda's runtime has no markdown library, so we render a practical subset:
# headings, fenced code blocks, inline code, bold, links, unordered lists, and
# paragraphs. Everything is HTML-escaped before inline formatting is applied.

_DOC_CSS = """
:root { color-scheme: light dark; }
body { max-width: 820px; margin: 2rem auto; padding: 0 1.2rem;
  font: 16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  color: #1c2024; background: #fff; }
h1 { font-size: 1.7rem; border-bottom: 2px solid #eaecef; padding-bottom: .3rem; }
h2 { font-size: 1.3rem; margin-top: 1.8rem; border-bottom: 1px solid #eaecef; padding-bottom: .2rem; }
h3 { font-size: 1.1rem; margin-top: 1.4rem; }
a { color: #0969da; }
code { background: #f3f4f6; padding: .15em .35em; border-radius: 4px;
  font: .9em "SF Mono",Menlo,Consolas,monospace; }
pre { background: #f6f8fa; padding: 1rem; border-radius: 8px; overflow-x: auto;
  border: 1px solid #e5e7eb; }
pre code { background: none; padding: 0; font-size: .87rem; line-height: 1.5; }
ul { padding-left: 1.4rem; }
.back { display: inline-block; margin-bottom: 1rem; font-size: .9rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e6edf3; background: #0d1117; }
  h1,h2 { border-color: #21262d; }
  code { background: #161b22; }
  pre { background: #161b22; border-color: #30363d; }
  a { color: #58a6ff; }
}
"""


def _inline_md(text: str) -> str:
    """Escape, then apply inline links / bold / code on a single line."""
    out = _html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        out,
    )
    return out


def _md_to_html(md: str, *, title: str = "Explanation", back_href: str = "") -> str:
    lines = md.split("\n")
    body: list[str] = []
    viz_ids: list[str] = []
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^```([\w-]*)\s*$", line)
        if fence:
            lang = fence.group(1)
            close_list()
            i += 1
            code: list[str] = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            raw_code = "\n".join(code)
            if lang == "algo-viz":
                try:
                    json.loads(raw_code)  # validate; fall back to <pre> if malformed
                    vid = f"algoviz-{len(viz_ids)}"
                    viz_ids.append(vid)
                    safe = raw_code.replace("</", "<\\/")  # keep it inside <script>
                    body.append(
                        f'<div data-algo-viz="{vid}-data"></div>'
                        f'<script type="application/json" id="{vid}-data">{safe}</script>'
                    )
                    continue
                except Exception:
                    pass  # malformed JSON -> render as a normal code block
            # language class lets highlight.js color it; bare fences (ASCII diagrams)
            # are marked nohighlight so they're left as-is.
            cls = f' class="language-{lang}"' if lang else ' class="nohighlight"'
            body.append("<pre><code" + cls + ">" + _html.escape(raw_code) + "</code></pre>")
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            close_list()
            level = len(h.group(1))
            body.append(f"<h{level}>{_inline_md(h.group(2))}</h{level}>")
            i += 1
            continue

        li = re.match(r"^\s*[-*]\s+(.*)$", line)
        if li:
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{_inline_md(li.group(1))}</li>")
            i += 1
            continue

        if line.strip() == "":
            close_list()
            i += 1
            continue

        close_list()
        body.append(f"<p>{_inline_md(line)}</p>")
        i += 1

    close_list()
    back = f'<a class="back" href="{_html.escape(back_href)}">&larr; Back to board</a>' if back_href else ""
    extra_css = ALGO_VIZ_CSS if viz_ids else ""
    extra_js = f"<script>{ALGO_VIZ_JS}</script>" if (viz_ids and ALGO_VIZ_JS) else ""
    # highlight.js (CDN): light/dark theme by system preference, run after body loads.
    hljs_css = (
        '<link rel="stylesheet" media="(prefers-color-scheme: light)" '
        'href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">'
        '<link rel="stylesheet" media="(prefers-color-scheme: dark)" '
        'href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">'
    )
    hljs_js = (
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>'
        '<script>if(window.hljs)hljs.highlightAll();</script>'
    )
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_html.escape(title)}</title>{hljs_css}<style>{_DOC_CSS}{extra_css}</style></head>"
        f"<body>{back}{''.join(body)}{extra_js}{hljs_js}</body></html>"
    )


def _extract_vizzes(md: str) -> list:
    """Pull every ```algo-viz JSON block out of a markdown doc, in order. Lets the
    board's flashcard modal mount a concept doc's live widget(s) inline without
    storing the (large) viz JSON in the deck files."""
    out: list = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        if re.match(r"^```algo-viz\s*$", lines[i]):
            i += 1
            buf: list = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            try:
                out.append(json.loads("\n".join(buf)))
            except Exception:
                pass
        else:
            i += 1
    return out


def _parse_flashcards(md: str) -> list:
    """Parse a `flashcards.md` deck into [{q, a}] pairs.

    Cards are delimited by the `Q:` marker (NOT by blank lines) — answers routinely
    contain blank lines around code snippets, so a blank line cannot end a card.
    Everything from a `Q:` up to the next `Q:` is one card; `A:` marks where the
    answer starts. Lines inside the deck's `<!-- … -->` helper header are skipped."""
    cards: list[dict] = []
    q = None
    a = None
    in_comment = False

    def flush():
        if q is not None and q.strip():
            cards.append({"q": q.strip(), "a": (a or "").strip()})

    for raw in md.split("\n"):
        line = raw.rstrip("\r")
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        st = line.strip()
        if st.startswith("Q:"):
            flush()
            q, a = st[2:].strip(), None
        elif st.startswith("A:"):
            a = st[2:].strip()
        elif a is not None:
            a += "\n" + line          # keep blank lines / indentation inside the answer
        elif q is not None and st:
            q += " " + st             # rare: a question wrapped across lines
    flush()
    return cards


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _deck_list(store) -> list:
    """Decks for the Study view: parse Overview.md's Sub-Categories table (name /
    last-quiz / best-score) and count live cards from each `{slug}/flashcards.md`."""
    decks: list = []
    try:
        md = store.read("Overview.md")
    except Exception:
        return decks
    for line in md.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 4:  # the Sub-Categories table; the Progress table has 5 cols
            continue
        name, _cards_col, lastq, best = cells
        if name.lower() == "sub-category" or set(name) <= set("-: "):  # header / separator
            continue
        slug = _slugify(name)
        key = f"{slug}/flashcards.md"
        cards = len(_parse_flashcards(store.read(key))) if store.exists(key) else 0
        decks.append({
            "topic": name, "slug": slug, "key": key, "cards": cards,
            "lastQuiz": "" if lastq in ("", "—") else lastq,
            "bestScore": "" if best in ("", "—") else best,
        })
    return decks


def handler(event, context):
    method, path, headers, qs = _event_bits(event)

    if method == "OPTIONS":
        return _resp(204, "", content_type="text/plain")

    if not BUCKET:
        return _resp(500, {"error": "BUCKET env not configured"})

    project = qs.get("project") or headers.get("x-board-project")
    if not project:
        return _resp(400, {"error": "missing project"})

    # ── Auth ──
    supplied = qs.get("k") or headers.get("x-board-secret") or ""
    expected = _expected_secret(project)
    if not expected or not hmac.compare_digest(supplied, expected):
        return _resp(403, {"error": "forbidden"})

    store = _store_for(project)

    try:
        if method == "GET" and path.rstrip("/") == "/api/board":
            return _resp(200, _board_payload(store, project))

        if method == "GET" and path.rstrip("/") == "/api/flashcards":
            # Parsed Q/A for a deck, so the board can show an in-page flip-card modal
            # instead of opening the raw flashcards.md file as a separate page.
            key = qs.get("key") or ""
            if not key.endswith(".md") or ".." in key or key.startswith("/"):
                return _resp(400, {"error": "invalid deck key"})
            if not store.exists(key):
                return _resp(404, {"error": f"deck {key} not found"})
            return _resp(200, {"key": key, "cards": _parse_flashcards(store.read(key))})

        if method == "GET" and path.rstrip("/") == "/api/decks":
            return _resp(200, {"decks": _deck_list(store)})

        if method == "GET" and path.rstrip("/") == "/api/viz":
            # algo-viz JSON blocks from a doc, so the flashcard modal can mount them inline.
            key = qs.get("key") or ""
            if not key.endswith(".md") or ".." in key or key.startswith("/"):
                return _resp(400, {"error": "invalid key"})
            if not store.exists(key):
                return _resp(404, {"error": f"doc {key} not found"})
            return _resp(200, {"key": key, "vizzes": _extract_vizzes(store.read(key))})

        if method == "GET" and path.rstrip("/") == "/doc":
            key = qs.get("key") or ""
            # Sandbox: serve any markdown doc inside the project (secret-gated).
            # Require .md (keeps .board-secret / *.json unreadable) and block traversal.
            if not key.endswith(".md") or ".." in key or key.startswith("/"):
                return _resp(400, {"error": "invalid doc key"})
            if not store.exists(key):
                return _resp(404, {"error": f"doc {key} not found"})
            md = store.read(key)
            title = key.rsplit("/", 1)[-1][:-3].replace("-", " ").title()
            back = f"/?project={project}&k={supplied}"
            page = _md_to_html(md, title=title, back_href=back)
            return _resp(200, page, content_type="text/html; charset=utf-8")

        if method == "GET" and not path.startswith("/api/"):
            html = kanban_core.render_board_html(project, secret=supplied)
            # bundle the algo-viz renderer so the flashcard modal can mount viz inline
            if ALGO_VIZ_CSS or ALGO_VIZ_JS:
                inject = f"<style>{ALGO_VIZ_CSS}</style><script>{ALGO_VIZ_JS}</script>"
                html = html.replace("</body>", inject + "</body>", 1)
            return _resp(200, html, content_type="text/html; charset=utf-8")

        if method == "PATCH" and "/api/items/" in path:
            item_id = path.split("/api/items/", 1)[1].strip("/")
            item_key = f"kanban/items/{item_id}.md"
            if not store.exists(item_key):
                return _resp(404, {"error": f"item {item_id} not found"})
            raw = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                import base64

                raw = base64.b64decode(raw).decode("utf-8")
            updates = json.loads(raw)
            kanban_core.update_item(store, item_key, updates)
            # INDEX.md is a human-readable mirror the UI never reads, and
            # regenerate_index() re-reads every item (~90 S3 GETs). Keeping it off
            # the edit hot path is the main latency fix; it's refreshed on add and
            # by the CLI. Just drop the stale board cache so the next load is fresh.
            _board_cache.pop(project, None)
            return _resp(200, {"ok": True})
    except Exception as exc:  # surface errors as JSON, not a 502
        return _resp(500, {"error": str(exc)})

    return _resp(404, {"error": "not found"})
