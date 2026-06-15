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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kanban_core  # noqa: E402
import storage  # noqa: E402

BUCKET = os.environ.get("BUCKET", "")
REGION = os.environ.get("REGION") or os.environ.get("AWS_REGION")

# Cache project secrets across warm invocations.
_secret_cache: dict[str, str] = {}

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
    i = 0
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^```(\w*)\s*$", line)
        if fence:
            close_list()
            i += 1
            code: list[str] = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            body.append("<pre><code>" + _html.escape("\n".join(code)) + "</code></pre>")
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
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_html.escape(title)}</title><style>{_DOC_CSS}</style></head>"
        f"<body>{back}{''.join(body)}</body></html>"
    )


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
            return _resp(200, kanban_core.load_board(store))

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
            kanban_core.regenerate_index(store)
            return _resp(200, {"ok": True})
    except Exception as exc:  # surface errors as JSON, not a 502
        return _resp(500, {"error": str(exc)})

    return _resp(404, {"error": "not found"})
