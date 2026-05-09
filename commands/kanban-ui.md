---
allowed-tools: Read, Glob, Bash(python3 *), Bash(open *), Bash(ls *), Bash(curl *), Bash(ps *)
argument-hint: [--port PORT]
description: Open the kanban board web UI for the loaded project, starting the server if needed
---

# Kanban UI — Open the Web Board

Arguments: $ARGUMENTS

#### Step 1: Resolve Project

Use the project already loaded in the current session context. Do not ask the user for a project name.

Look for `--port {N}` in $ARGUMENTS to override the default port (7331).

Verify `~/.claude/contexts/{project}/kanban/` exists. If not, tell the user:
> "No kanban board configured for '{project}'. Run `/pensare:setup` and enable kanban when prompted."

Stop if kanban folder is missing.

#### Step 2: Check if Server is Already Running

Run:
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:{port}/api/board
```

If the response is `200`, the server is already up. Just open the browser:
```bash
open http://localhost:{port}
```

Tell the user:
> "Kanban board is already running — opened http://localhost:{port}"

Done.

#### Step 3: Start the Server (only if not already running)

Find the server script at `~/.claude/plugins/pensare/kanban-server.py`.

Run: `ls ~/.claude/plugins/pensare/kanban-server.py 2>/dev/null` to check existence.

If not found, tell the user:
> "Could not find kanban-server.py. Re-run `install.sh` from the pensare plugin directory to reinstall."
Stop.

Start the server in the background:
```bash
python3 ~/.claude/plugins/pensare/kanban-server.py {project} --port {port} &
```

The server opens the browser automatically after a short delay.

Tell the user:
> "Kanban board starting at http://localhost:{port}
> Project: {project}
> Source: ~/.claude/contexts/{project}/kanban/
>
> Auto-refreshes every 30 seconds. To stop: kill the kanban-server.py process."

#### Notes for the user

- This command is idempotent — safe to run whether the server is already running or not.
- Items are read live from `kanban/items/` — no sync required.
- Use `/pensare:kanban-add` and `/pensare:kanban-update` to create and move items.
- The board is view-only. All editing is done via pensare commands.
- To stop the server: `ps aux | grep kanban-server` then `kill {PID}`.
