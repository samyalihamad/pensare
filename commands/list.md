---
allowed-tools: Read, Glob, Bash(ls *)
description: List all pensare projects and context files
---

# List — Show Projects

Arguments: $ARGUMENTS

1. Scan `~/.claude/contexts/` for project folders (dirs with `sources.json`) and standalone `.md` files
2. Display each project with file count, last sync date, context file descriptions, source counts, and storage mode (local or git)
3. For each project, show journal status:
   - **If `journal/manifest.json` exists (three-tier format):** Read the manifest and show:
     - Hot entries: `{N} entries across {M} weeks` (count `hot_files` entries)
     - KB files: `{N} KB topics` (count `kb_files` entries)
     - Last compacted: `{date}` or `never` (from `last_compaction` field)
   - **If legacy `journal.md` exists without `journal/` directory:** Count lines and show:
     - Journal: `{N} lines (legacy — run /pensare compact to migrate)`
4. Show standalone files with last modified date
