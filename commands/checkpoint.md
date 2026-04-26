---
allowed-tools: Bash(git *), Bash(mkdir *), Read, Write, Edit, Glob
description: Auto-save un-journaled session state to the project journal
---

# Checkpoint Session State

Automatically captures work from the current session that has not yet been journaled. This command takes no arguments.

## Step 1: Resolve Project

Determine which project to write to without requiring the user to specify. Check in order:

1. A project context was already loaded/synced in this session — use it.
2. Only one project exists under `~/.claude/contexts/` — use it.
3. Otherwise, list available projects and ask the user to clarify.

## Step 2: Scan for Un-Journaled Items

Review the ENTIRE conversation history. Extract items that are NOT already captured in existing journal entries. To avoid duplicates, read the current week's journal file (if it exists) and compare against what has already been recorded.

Look for:

- Code TODOs or FIXMEs discovered during the session
- Code changes made (files created, modified, deleted)
- Bugs, issues, or gaps found
- Decisions made (even informal ones)
- Blocked items or open questions
- Test results not yet journaled

If nothing new is found, print:

> Nothing un-journaled — checkpoint skipped.

Then stop. Do NOT write an empty entry.

## Step 3: Write Checkpoint Entry

Use the same journal write path as the `note` command.

Compute the current ISO 8601 week identifier: `YYYY-WNN`. Handle year boundaries correctly — Dec 29-31 may belong to W01 of the next year, and Jan 1-3 may belong to W52 or W53 of the previous year. Use the ISO year, not the calendar year.

Create the `journal/` directory inside the project if it does not exist.

File path: `journal/{week}.md` (e.g., `journal/2026-W17.md`).

If the file does not exist, create it with this header:

```
# Journal — Week of {Monday date of the ISO week, YYYY-MM-DD}
```

Tag: **CHECKPOINT**

Append the entry in this format, including ONLY sections that have content:

```
### {YYYY-MM-DD HH:MM} — CHECKPOINT: Session state capture

**Code changes this session:**
- {file path}: {what changed}

**TODOs discovered:**
- {file:line}: {TODO text}

**Issues/gaps found:**
- {description}

**Decisions made:**
- {decision and rationale}

**Blocked on:**
- {item} — {who/what is blocking}

**References:** {file paths, PR numbers, people mentioned}
```

Omit any section that has no items. For example, if no TODOs were discovered and nothing is blocked, leave out those sections entirely.

Update `journal/manifest.json` the same way as the `note` command:

- If `manifest.json` does not exist, create it with `{"hot_files": [], "kb_files": []}`.
- Find or create the `hot_files` entry whose `week` matches the current week.
- Increment `entries` count (or set to 1 if new).
- Update `date_range` to cover the earliest and latest entry dates for this week.
- Append `CHECKPOINT` to the `tags` array (deduplicated).
- Rewrite `one_line` as a comma-separated summary, max 120 characters.

### Legacy fallback

If `journal.md` exists in the project root AND the `journal/` directory does NOT exist, append to `journal.md` instead. Print:

> Tip: Run `/pensare compact` to migrate to three-tier journal format.

### Git auto-commit

If `sources.json` exists and contains `"storage": "git"`, run:

```bash
git add -A
git commit -m "pensare checkpoint: session state capture"
git push
```

## Step 4: Confirm

Print a single confirmation line:

> Checkpoint saved: {N} items captured.

Where N is the total count of items across all sections in the entry.
