---
allowed-tools: Read, Write, Edit, Glob, Bash(date *), Bash(ls *)
argument-hint: ["title"]
description: Add a new work item to the kanban board of the loaded project
---

## Kanban Data Structure

Work items live in `~/.claude/contexts/{project}/kanban/`.

```
kanban/
├── config.json    # columns, categories, id_prefix, next_id
├── INDEX.md       # Board summary for Claude
└── items/
    ├── KB-001.md
    └── ...
```

**config.json schema:**
```json
{
  "columns": ["Backlog", "In Progress", "Blocked", "Done"],
  "categories": ["Feature", "Bug"],
  "id_prefix": "KB",
  "next_id": 1
}
```

**Item file format** (`{id_prefix}-{NNN}.md`, zero-padded to 3 digits):
```
---
id: KB-001
title: "Title here"
status: backlog
category: Feature
priority: medium
created: 2026-05-09
updated: 2026-05-09
---

## Description

...

## Notes

- 2026-05-09: Created
```

Status values are column names lowercased and hyphenated:
`Backlog` → `backlog`, `In Progress` → `in-progress`, `Blocked` → `blocked`, `Done` → `done`

# Kanban Add — Create a Work Item

Arguments: $ARGUMENTS

#### Step 1: Resolve Project

Use the project already loaded in the current session context. Do not ask the user for a project name.

Read `~/.claude/contexts/{project}/kanban/config.json`.

If the `kanban/` directory does not exist for this project, tell the user:
> "No kanban board found for '{project}'. Run `/pensare:setup` and enable kanban when prompted."

Stop here if kanban is not configured.

#### Step 2: Collect Item Details

If $ARGUMENTS is non-empty, use the full argument string as the title. Otherwise ask: **"Title for this work item?"**

Show the available categories from `config.json`. Ask: **"Category? [{category list, or 'none' if empty}] (press enter to skip)"**

Ask: **"Priority? high / medium / low (default: medium)"** — accept empty input as `medium`.

Ask: **"Initial description? (optional — press enter to skip)"**

#### Step 3: Assign ID and Create File

Read `config.json`. Get `id_prefix` and `next_id`. Format the ID as `{prefix}-{NNN}` (zero-pad `next_id` to 3 digits, e.g. `1` → `001`).

The initial status is the first column name lowercased and hyphenated.

Get today's date: run `date +%Y-%m-%d`.

Write `~/.claude/contexts/{project}/kanban/items/{id}.md`:
```
---
id: {id}
title: "{title}"
status: {initial_status}
category: {category or empty string}
priority: {priority}
created: {today}
updated: {today}
---

## Description

{description if provided, otherwise empty}

## Notes

- {today}: Created
```

Increment `next_id` by 1 and write `config.json` back.

#### Step 4: Regenerate INDEX.md

Read all `*.md` files in `kanban/items/`. Parse the YAML frontmatter block (lines between the first `---` and the second `---`) from each file.

Build `~/.claude/contexts/{project}/kanban/INDEX.md`:

```markdown
# Kanban Board — {project}

_Last updated: {today}_

## Column Summary

| Column | Count |
|--------|-------|
| Backlog | N |
| In Progress | N |
| Blocked | N |
| Done | N |

## Active Items

Sort non-Done items by priority (high → medium → low), then by updated date descending.

| ID | Title | Status | Category | Priority |
|----|-------|--------|----------|----------|
| KB-003 | ... | In Progress | Feature | high |

## Recently Completed (last 5)

Sort Done items by updated date descending. Show at most 5.

| ID | Title | Category | Updated |
|----|-------|----------|---------|
```

#### Step 5: Confirm

Tell the user:
> "Created **{id}: {title}** → {first column name} ({priority} priority).
> Run `/pensare:kanban-update {id}` to change status or add notes."
