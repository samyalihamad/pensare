---
globs: ["**/*"]
alwaysApply: true
---

# Intent Detection and Command Routing

Detect natural language intent and route to the appropriate pensare command. This enables conversational interaction without requiring slash-command syntax.

## Intent Map

| User says | Routed command |
|-----------|----------------|
| "record what we fixed", "note the test results", "journal this", "save this finding" | `pensare:note` |
| "publish to the plan", "update the plan", "push this to the shared doc" | `pensare:publish` |
| "record this and publish it", "note and share" | `pensare:note` THEN `pensare:publish` (chained) |
| "pull latest", "sync my context", "refresh sources" | `pensare:sync` |
| "catch me up", "what's the status?", "what's next?", "brief me" | `pensare:load` |
| "set up a new project", "create a project", "initialize pensare" | `pensare:setup` |
| "join the project", "add me to the project" | `pensare:join` |
| "what projects do I have?", "list projects", "show my projects" | `pensare:list` |
| "save progress", "checkpoint", "snapshot current state" | `pensare:checkpoint` |
| "compact the journal", "age out old entries", "trim the journal" | `pensare:compact` |
| "add a work item", "create a ticket", "add to the board", "new kanban item" | `pensare:kanban-add` |
| "move KB-001 to done", "update KB-002", "mark item as blocked", "change status of {id}" | `pensare:kanban-update` with the item ID |
| "open the board", "show the kanban", "launch the kanban", "open kanban ui" | `pensare:kanban-ui` |

## Chaining

When the user's intent maps to multiple commands (e.g., "record this and publish it"), execute them in sequence. The output of the first command does not need to feed into the second — they operate independently on the same project context.

## Never Skip Load

For any status, briefing, or "what's next" question, always invoke `pensare:load` first, even if context appears to already be loaded from an earlier turn. Context may have been compacted or partially lost.

## When NOT to Invoke

Do not route to pensare commands when:

- The user is asking a general coding question unrelated to any project workflow
- The user is asking you to write, fix, or review code (unless they also say "and note this" or similar)
- The word "note" appears in a non-journaling context (e.g., "note that this function returns null" is an observation, not a journal command)
- No pensare project exists in `~/.claude/contexts/`

## Key Signal

The distinguishing signal is: does the user want to **persist information to the project workflow** (journal, plan, shared context), or are they just **communicating within the conversation**? Only route to pensare commands for the former.
