#!/usr/bin/env python3
"""Offline edit + sync for a pensare project (markdown source of truth in S3).

  pull:  download all project .md files to a local mirror + record a manifest of hashes.
  push:  upload locally-changed files back to S3. Safe by default — if a file ALSO changed
         remotely since you pulled, it's flagged as a conflict and skipped (use --force).

Workflow:  (online) pull  ->  (offline, on the plane) edit the .md files  ->  (online) push

Usage:
  python3 sync_offline.py --project interview-prep --dir ~/ip-mirror pull
  python3 sync_offline.py --project interview-prep --dir ~/ip-mirror push [--force] [--dry-run]
"""
import argparse, hashlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STORAGE = os.path.join(os.path.dirname(HERE), "lib", "storage.py")
PREFIXES = ["", "concepts", "concepts/dsa", "concepts/build", "concepts/python",
            "explanations", "kb", "kanban/items", "coding-prep/programming-concepts",
            "coding-prep/problems/anthropic", "inference-eval", "behavioral", "system-design"]

def sh(project, *args, inp=None):
    return subprocess.run(["python3", STORAGE, "--project", project, *args],
                          capture_output=True, text=True)
def h(s): return hashlib.sha256(s.encode()).hexdigest()

def dump(project, prefix):
    out = sh(project, "dump", "--prefix", prefix, "--glob", "*.md").stdout
    docs, cur, buf = {}, None, []
    for line in out.split("\n"):
        m = re.match(r"^===== PENSARE-FILE: (.+?) =====$", line)
        if m:
            if cur is not None: docs[cur] = "\n".join(buf)
            cur, buf = m.group(1), []
        elif cur is not None: buf.append(line)
    if cur is not None: docs[cur] = "\n".join(buf)
    return docs

def all_remote(project):
    docs = {}
    for p in PREFIXES: docs.update(dump(project, p))
    return docs

def pull(project, d):
    docs = all_remote(project)
    manifest = {}
    for key, content in docs.items():
        path = os.path.join(d, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(content)
        manifest[key] = h(content)
    json.dump(manifest, open(os.path.join(d, ".manifest.json"), "w"))
    print(f"pulled {len(docs)} files to {d}")

def push(project, d, force, dry):
    mpath = os.path.join(d, ".manifest.json")
    if not os.path.exists(mpath):
        sys.exit("no .manifest.json — run pull first")
    manifest = json.load(open(mpath))
    # collect local files
    local = {}
    for root, _, files in os.walk(d):
        for f in files:
            if not f.endswith(".md") or f == "INDEX.md": continue   # INDEX is generated
            p = os.path.join(root, f); key = os.path.relpath(p, d)
            local[key] = open(p).read()
    uploaded, conflicts, unchanged, new = [], [], 0, []
    for key, content in local.items():
        base = manifest.get(key)
        if base is not None and h(content) == base:
            unchanged += 1; continue                 # not edited offline
        # changed locally (or new)
        if base is None:
            new.append(key)
        else:
            remote = sh(project, "read", "--key", key).stdout
            if h(remote) != base and not force:
                conflicts.append(key); continue       # changed both places
        if not dry:
            # upload via real stdin redirection from the local file (never empty)
            with open(os.path.join(d, key)) as fh:
                rr = subprocess.run(["python3", STORAGE, "--project", project, "write",
                                     "--key", key, "--stdin"], stdin=fh,
                                    capture_output=True, text=True)
            if rr.returncode != 0: conflicts.append(key + " (write failed)"); continue
            manifest[key] = h(content)
        uploaded.append(key)
    if not dry: json.dump(manifest, open(mpath, "w"))
    print(f"{'DRY-RUN ' if dry else ''}pushed: {len(uploaded)} (new: {len(new)}), "
          f"unchanged: {unchanged}, conflicts: {len(conflicts)}")
    for k in uploaded: print(f"  ↑ {k}")
    for k in conflicts: print(f"  ⚠ CONFLICT (changed remotely too, skipped): {k}")
    if conflicts and not force: print("  re-pull or use --force to overwrite remote.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("cmd", choices=["pull", "push"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = os.path.expanduser(a.dir); os.makedirs(d, exist_ok=True)
    if a.cmd == "pull": pull(a.project, d)
    else: push(a.project, d, a.force, a.dry_run)

if __name__ == "__main__":
    main()
