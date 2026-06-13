#!/usr/bin/env python3
"""
Pensare storage abstraction.

Selects a backend (local filesystem or AWS S3) from a project's sources.json and
exposes a uniform read/write/ls/exists/rm/dump interface. Used two ways:

  1. As a LIBRARY  — imported by lib/kanban_core.py and lib/lambda_handler.py.
  2. As a CLI      — invoked from prompt-driven command markdown, e.g.
                       python3 ${CLAUDE_PLUGIN_ROOT}/lib/storage.py read \
                         --project my-proj --key journal/2026-W24.md

Keys are always project-relative POSIX paths (e.g. "journal/2026-W24.md",
"kanban/items/KB-001.md", "sources.json"). The backend joins them onto the local
project directory or the S3 prefix.

Backend selection (from ~/.claude/contexts/<project>/sources.json):
  - "local" / "git"  -> LocalBackend (the git symlink already makes this transparent)
  - "s3"             -> S3Backend(bucket, prefix, region)

In S3 mode a thin local STUB sources.json still lives at
~/.claude/contexts/<project>/sources.json so the backend can be located offline.
The authoritative sources.json lives in S3 and is read/written via the backend.

No third-party deps for local mode. S3 mode needs boto3 (present in the Lambda
runtime; `pip install boto3` on a dev machine).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

CONTEXTS_ROOT = Path(os.path.expanduser("~/.claude/contexts"))

# A delimiter that will not appear in normal markdown, used by `dump` to pack
# multiple files into one stdout stream the caller can split on.
DUMP_DELIM = "\n===== PENSARE-FILE: {key} =====\n"


# ── Backends ─────────────────────────────────────────────────────────────────


class LocalBackend:
    """Project data on the local filesystem under ~/.claude/contexts/<project>/."""

    kind = "local"

    def __init__(self, project: str, root: Path | None = None):
        self.project = project
        self.root = (root or (CONTEXTS_ROOT / project)).resolve()

    def _path(self, key: str) -> Path:
        # Reject path traversal; keys are always project-relative.
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"key escapes project root: {key!r}")
        return p

    def read(self, key: str) -> str:
        return self._path(key).read_text()

    def write(self, key: str, content: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def ls(self, prefix: str = "", glob: str | None = None) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        out: list[str] = []
        for f in sorted(base.rglob("*") if glob else base.iterdir()):
            if f.is_dir():
                continue
            if glob and not fnmatch.fnmatch(f.name, glob):
                continue
            out.append(f.relative_to(self.root).as_posix())
        return out

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def rm(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Backend:
    """Project data in a shared S3 bucket under a per-project prefix."""

    kind = "s3"

    def __init__(self, project: str, bucket: str, prefix: str, region: str | None = None):
        import boto3  # imported lazily so local mode needs no boto3

        self.project = project
        self.bucket = bucket
        # Normalise prefix to end with exactly one slash (or be empty).
        self.prefix = (prefix or "").lstrip("/")
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix += "/"
        self.region = region
        self._s3 = boto3.session.Session(region_name=region).client("s3")

    def _full(self, key: str) -> str:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"invalid key: {key!r}")
        return f"{self.prefix}{key}"

    def read(self, key: str) -> str:
        from botocore.exceptions import ClientError

        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=self._full(key))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(key) from exc
            raise
        return obj["Body"].read().decode("utf-8")

    def write(self, key: str, content: str) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self._full(key),
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8"
            if key.endswith(".md")
            else "application/json"
            if key.endswith(".json")
            else "text/plain; charset=utf-8",
        )

    def ls(self, prefix: str = "", glob: str | None = None) -> list[str]:
        full_prefix = self._full(prefix) if prefix else self.prefix
        paginator = self._s3.get_paginator("list_objects_v2")
        out: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(self.prefix):]
                if not rel or rel.endswith("/"):
                    continue
                if glob and not fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob):
                    continue
                out.append(rel)
        return sorted(out)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._full(key))
            return True
        except ClientError:
            return False

    def rm(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._full(key))


# ── Resolution ───────────────────────────────────────────────────────────────


def _stub_path(project: str) -> Path:
    return CONTEXTS_ROOT / project / "sources.json"


def load_stub(project: str) -> dict:
    """Read the local (stub or full) sources.json that locates the backend."""
    p = _stub_path(project)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def get_store(project: str):
    """Construct the backend for a project from its local sources.json."""
    cfg = load_stub(project)
    mode = cfg.get("storage", "local")
    if mode == "s3":
        s3 = cfg.get("s3", {})
        bucket = s3.get("bucket")
        if not bucket:
            raise ValueError(
                f"project {project!r} has storage:s3 but no s3.bucket in sources.json"
            )
        return S3Backend(
            project,
            bucket=bucket,
            prefix=s3.get("prefix", f"contexts/{project}/"),
            region=s3.get("region"),
        )
    # local and git both use the local filesystem (git via the contexts symlink).
    return LocalBackend(project)


def store_for_s3(project: str, bucket: str, prefix: str, region: str | None = None):
    """Direct S3 store constructor (used by the Lambda, which has no local stub)."""
    return S3Backend(project, bucket=bucket, prefix=prefix, region=region)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _read_stdin() -> str:
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storage.py", description="Pensare storage CLI")
    parser.add_argument("--project", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("backend", help="print 'local' or 's3'")

    p_read = sub.add_parser("read", help="print file content to stdout")
    p_read.add_argument("--key", required=True)

    p_write = sub.add_parser("write", help="write content (from --file or --stdin)")
    p_write.add_argument("--key", required=True)
    src = p_write.add_mutually_exclusive_group(required=True)
    src.add_argument("--file")
    src.add_argument("--stdin", action="store_true")

    p_ls = sub.add_parser("ls", help="list keys under a prefix")
    p_ls.add_argument("--prefix", default="")
    p_ls.add_argument("--glob")

    p_exists = sub.add_parser("exists", help="exit 0 if key exists else 1")
    p_exists.add_argument("--key", required=True)

    p_rm = sub.add_parser("rm", help="delete a key")
    p_rm.add_argument("--key", required=True)

    p_dump = sub.add_parser("dump", help="concatenate many files in one process")
    p_dump.add_argument("--prefix", default="")
    p_dump.add_argument("--glob")

    args = parser.parse_args(argv)

    # `backend` only needs the stub, not a live S3 client.
    if args.cmd == "backend":
        print(load_stub(args.project).get("storage", "local"))
        return 0

    store = get_store(args.project)

    if args.cmd == "read":
        try:
            sys.stdout.write(store.read(args.key))
        except FileNotFoundError:
            print(f"not found: {args.key}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "write":
        content = _read_stdin() if args.stdin else Path(args.file).read_text()
        store.write(args.key, content)
        return 0

    if args.cmd == "ls":
        for k in store.ls(args.prefix, args.glob):
            print(k)
        return 0

    if args.cmd == "exists":
        return 0 if store.exists(args.key) else 1

    if args.cmd == "rm":
        store.rm(args.key)
        return 0

    if args.cmd == "dump":
        for k in store.ls(args.prefix, args.glob):
            sys.stdout.write(DUMP_DELIM.format(key=k))
            try:
                sys.stdout.write(store.read(k))
            except FileNotFoundError:
                pass
        return 0

    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
