---
allowed-tools: Read, Write, Edit, Glob, Bash(date *), Bash(ls *)
argument-hint: [item-id]
description: Update a kanban work item — change status, priority, title, or add a note
---

## Kanban Data Structure

Work items live in `~/.claude/contexts/{project}/kanban/items/{id}.md`.
See `/pensare:kanban-add` for the full data structure reference.

Status slugs: `backlog`, `in-progress`, `blocked`, `done`
(derived from column names: lowercased, spaces → hyphens)

# Kanban Update — Edit a Work Item

Arguments: $ARGUMENTS

#### Step 1: Resolve Project and Item

Use the project already loaded in the current session context. Do not ask the user for a project name.

Read `~/.claude/contexts/{project}/kanban/config.json`.

If the `kanban/` directory does not exist, tell the user kanban is not configured for this project and stop.

If $ARGUMENTS contains an item ID matching `[A-Z]+-\d+` (case-insensitive), use that item. Look for `kanban/items/{ID}.md`. If not found, say so and stop.

If no item ID was given, read all `*.md` files in `kanban/items/`, parse frontmatter, filter to non-Done items, and display:

```
Active items in {project}:
  KB-001  in-progress  high    Add OAuth login
  KB-002  backlog      medium  Dark mode support
  KB-003  blocked      high    Fix crash on empty input

Which item do you want to update? (enter ID)
```

Wait for the user's ID selection, then proceed.

#### Step 2: Show Current State and Ask What to Update

Read and parse the item file. Print the current fields:

```
KB-001: Add OAuth login
  Status:   in-progress
  Category: Feature
  Priority: high
  Updated:  2026-05-09
```

Ask:
```
What would you like to update? (enter one or more numbers, comma-separated)
  1. Status    (current: {status})
  2. Priority  (current: {priority})
  3. Add a note
  4. Edit title
```

#### Step 3: Apply Changes

Get today's date: run `date +%Y-%m-%d`.

For each selected option:

**1. Status** — Show the columns from `config.json` numbered. Mark the current one with `←`. Let the user pick by number or by typing the column name. Convert the chosen column name to its status slug (lowercase, spaces → hyphens).

**2. Priority** — Ask: "New priority? high / medium / low". Accept `h`, `m`, `l` as shorthand.

**3. Add a note** — Ask: "Note text?" Append the line `- {today}: {note}` under the `## Notes` section of the item body. If no `## Notes` section exists, append one.

**4. Edit title** — Ask: "New title?" Update the `title` field in frontmatter.

After all edits: update the `updated` field in frontmatter to today's date.

Write the modified item file back. Preserve all other frontmatter fields and the body exactly.

**Frontmatter edit approach:** Read the raw file content. Replace only the changed frontmatter lines between the first and second `---` delimiters. Do not reformat or reorder unaffected fields.

#### Step 4: Regenerate INDEX.md

Read all `*.md` files in `kanban/items/`. Parse frontmatter from each.

Rebuild `~/.claude/contexts/{project}/kanban/INDEX.md` using the same format as `kanban-add`:

```markdown
# Kanban Board — {project}

_Last updated: {today}_

## Column Summary

| Column | Count |
|--------|-------|
...

## Active Items
(non-Done, sorted: high priority first, then by updated date descending)

| ID | Title | Status | Category | Priority |
...

## Recently Completed (last 5)
(Done items, sorted by updated date descending, at most 5)

| ID | Title | Category | Updated |
...
```

Write the updated INDEX.md.

#### Step 5: Confirm

Print a concise summary of what changed, e.g.:
> "Updated **KB-001: Add OAuth login** — status: `in-progress` → `done`, note added."
