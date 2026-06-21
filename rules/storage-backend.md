# Storage backend (local / git / S3)

Pensare projects store data in one of three backends, recorded as `storage` in the
project's `~/.claude/contexts/{project}/sources.json`:

- `local` (default) and `git` — data lives on the local filesystem under
  `~/.claude/contexts/{project}/` (git mode uses a symlink). Use the normal
  Read / Write / Edit / Glob tools exactly as before. **Nothing changes.**
- `s3` — data lives in an S3 bucket. The local `sources.json` is only a *stub*
  that names the bucket; the real files (journal, kb, Overview, kanban, the full
  sources.json) are in S3 and must be accessed through the storage helper, **not**
  the Read/Write/Glob tools.

## When `storage` is `s3`, use the storage helper for project files

All project-relative file I/O goes through:

```
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/pensare}/lib/storage.py --project {project} <cmd> ...
```

`${CLAUDE_PLUGIN_ROOT}` is only set inside the plugin's own hooks, **not** in the
Bash tool — so the `:-$HOME/.claude/plugins/pensare` fallback (the canonical install
location, real dir or dev symlink) is what makes these commands run. Keep it on every
invocation; the var does not persist across Bash calls.

| Need | Command |
|------|---------|
| Detect backend first | `... --project {p} backend` → prints `local` or `s3` |
| Read a file | `... --project {p} read --key journal/2026-W24.md` (exit 1 if missing) |
| Write a file (from stdin) | `printf '%s' "$CONTENT" \| python3 .../storage.py --project {p} write --key Overview.md --stdin` |
| List files | `... --project {p} ls --prefix kb --glob '*.md'` |
| Bulk-read many files in one call (use for load) | `... --project {p} dump --prefix '' --glob '*.md'` |
| Check existence | `... --project {p} exists --key sources.json` (exit code) |
| Delete | `... --project {p} rm --key kb/old.md` |

Keys are always project-relative POSIX paths (e.g. `journal/2026-W24.md`,
`kanban/items/KB-001.md`, `sources.json`). Read-modify-write means: `read` the
current content, compute the new full content, then `write --stdin`.

## Kanban on S3

For kanban add/update on an `s3` project, do **not** hand-write item files — call
the shared core so the model and the online board use identical logic:

```
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/pensare}/lib/kanban_core.py --project {p} add \
  --title "..." [--category C] [--priority high|medium|low] [--description "..."]
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/pensare}/lib/kanban_core.py --project {p} update \
  --id KB-001 [--status s] [--priority p] [--title t] [--note "..."]
```

Both write to S3 and regenerate `kanban/INDEX.md` automatically.

## Notes

- S3 writes are durable immediately — for `s3` projects **skip** the git
  auto-commit step that local/git modes run after note/checkpoint/sync.
- S3 needs `boto3` on this machine (`pip3 install boto3`); the Lambda has it built in.
- Setting up S3 storage / online kanban is handled by `deploy/bootstrap.sh` (once)
  and `deploy/provision-project.sh {project} [--kanban]` (per project), which
  `/pensare setup` calls for you.
