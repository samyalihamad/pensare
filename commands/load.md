---
allowed-tools: Read, Glob, Bash(ls *), Bash(python3 *)
argument-hint: <keyword>
description: Load project context and journal into the current session
---

# Load Project Context

Follow these steps exactly to load a Pensare project into the current session.

> **S3-backed projects** (see the **Storage backend** rule): if the resolved project's
> `sources.json` has `storage: "s3"`, read its files through the storage helper instead of
> Read/Glob. Fastest is one bulk call: `python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/pensare}/lib/storage.py --project {project} dump --prefix '' --glob '*.md'` for root context files, plus `... read --key journal/manifest.json` and `... read --key journal/{week}.md` for the journal. Everything else in the steps below is identical.

## Step 1: Find Project

Search `~/.claude/contexts/*/` for directories matching the user's keyword (case-insensitive).

- If only one project directory exists under `~/.claude/contexts/`, use it regardless of keyword.
- If multiple directories exist, match the keyword against:
  - The project directory name
  - Names of `*.md` files in the project root
  - The `description` field in `sources.json` if it exists
- If no match or ambiguous, list the available projects and ask the user to clarify.

## Step 2: Read Context Files and Journal (Three-Tier Loading)

### Context files
Read all `*.md` files in the project root directory. Exclude files inside `journal/` and `kb/` subdirectories — those are loaded separately below.

### Hot journal (Tier 1)
If `journal/manifest.json` exists in the project directory:
- Compute the current ISO 8601 week (YYYY-WNN) and the previous week.
- Read the current week file (`journal/{week}.md`) in full.
- Read the previous week file in full.
- For older weeks (weeks 3-4 back): show only the `one_line` summary from `manifest.json`. Do not read the files.

### Knowledge base (Tier 2)
Read the `kb_files` array from `manifest.json`. Present each KB entry as its topic name with its `one_line` summary. Do NOT read KB files by default.

Exception: if the user's load keyword matches a KB file's `topic` or any item in its `entities` array (case-insensitive substring match), THEN read that KB file in full and include its content.

### Legacy fallback
If `journal.md` exists in the project root AND the `journal/` directory does NOT exist, read `journal.md` directly. Print:

> Tip: Run `/pensare compact` to migrate to three-tier journal format.

## Step 3: Activate Project

Read `sources.json` in the project directory. If it contains a `working_directory` field, print it as the project root so the user knows where code lives.

## Step 4: Present Briefing

Output a structured briefing in this format:

```
## Current Status
(synthesized from context files)

## Recent Activity (This Week)
(full entries from current week journal)

## Last Week
(full entries from previous week)

## Earlier This Month (summaries)
(one_line from manifest for older weeks)

## Knowledge Base (distilled from older entries)
(topic list with one-line summaries; matched topics shown in full)
```

Target 300-500 lines total. If the current week exceeds 200 lines, summarize older weeks more aggressively to stay within budget.

End with: **"Context loaded. Ready to continue."**
