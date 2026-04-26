---
allowed-tools: Bash(git *), Bash(mkdir *), Read, Write, Edit, Glob
argument-hint: <instruction>
description: Add a journal entry — Claude reviews the session and composes a structured note
---

# Add a Journal Entry

The argument is an INSTRUCTION (e.g., "record what we fixed"), not the note text itself. Claude reviews the entire conversation, follows the instruction, and composes the entry.

## Step 1: Resolve Project

Determine which project to write to without requiring the user to specify. Check in order:

1. A project context was already loaded/synced in this session — use it.
2. The argument starts with a known project name — use that project.
3. Only one project exists under `~/.claude/contexts/` — use it.
4. Otherwise, list available projects and ask the user to clarify.

## Step 2: Review Conversation and Compose

Review the ENTIRE conversation history. Follow the user's instruction to decide what to capture. Auto-detect and include any of the following that are relevant:

- Test results (pass/fail, metrics, durations)
- Errors encountered and how they were fixed
- PRs or commits referenced
- People mentioned
- Decisions made and their rationale

Assign exactly one tag to the entry based on its primary content:

| Tag        | Use when                                      |
|------------|-----------------------------------------------|
| TEST       | Test results, benchmarks, evaluations          |
| ERROR      | Errors encountered, stack traces               |
| FIX        | Bug fixes, workarounds applied                 |
| BLOCKER    | Blocked items, waiting on external dependency  |
| DECISION   | Architecture or process decisions              |
| NOTE       | General observations, context, anything else   |

## Step 3: Write to Journal (Three-Tier)

Compute the current ISO 8601 week identifier: `YYYY-WNN`. Handle year boundaries correctly — Dec 29-31 may belong to W01 of the next year, and Jan 1-3 may belong to W52 or W53 of the previous year. Use the ISO year, not the calendar year.

Create the `journal/` directory inside the project if it does not exist.

File path: `journal/{week}.md` (e.g., `journal/2026-W17.md`).

If the file does not exist, create it with this header:

```
# Journal — Week of {Monday date of the ISO week, YYYY-MM-DD}
```

Append the entry in this format:

```
### {YYYY-MM-DD HH:MM} — {TAG}: {one-line summary}

{Composed note body with structured formatting — bullet lists, code blocks, etc.}

**References:** {PR numbers, file paths, people mentioned}
```

Then update `journal/manifest.json`:

- If `manifest.json` does not exist, create it with `{"hot_files": [], "kb_files": []}`.
- Find or create the `hot_files` entry whose `week` matches the current week.
- Increment `entries` count (or set to 1 if new).
- Update `date_range` to cover the earliest and latest entry dates for this week.
- Append any new tags to the `tags` array (deduplicated).
- Rewrite `one_line` as a comma-separated summary of tag + summary pairs, max 120 characters.

### Legacy fallback

If `journal.md` exists in the project root AND the `journal/` directory does NOT exist, append to `journal.md` instead. Print:

> Tip: Run `/pensare compact` to migrate to three-tier journal format.

## Step 4: Git Auto-Commit

If `sources.json` exists and contains `"storage": "git"`, run:

```bash
git add -A
git commit -m "pensare note: {TAG} {one-line summary}"
git push
```

## Step 5: Confirm

Print the composed note so the user can review it. Then print the journal file path and current entry count for the week.
