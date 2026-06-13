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
import json
import os
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
