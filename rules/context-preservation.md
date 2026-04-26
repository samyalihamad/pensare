---
globs: ["**/*"]
alwaysApply: true
---

# Context Preservation

Pensare automatically checkpoints project context at key moments. These checkpoints are proactive — they do not require user action.

## Auto-Checkpoint Triggers

1. **Before context compaction** (HIGHEST priority) — When the conversation is about to be compacted, immediately write all pending findings, decisions, and open questions to the project journal. This is the most critical trigger because compaction discards conversation history.

2. **After subagent completion with new findings** — When a subagent returns results that contain new information (code discoveries, test results, error patterns), checkpoint the findings before continuing.

3. **After significant discoveries** — When the conversation surfaces a meaningful insight (a bug root cause, an architectural decision, a key dependency, a performance finding), capture it immediately rather than waiting.

4. **Every ~30 minutes of active work** — During long sessions, periodically checkpoint accumulated context. Track elapsed time and write a checkpoint when roughly 30 minutes of active work have passed since the last one.

5. **Before ending a session** — When the user signals they are done ("thanks", "that's all", "signing off"), checkpoint any un-saved context before the session closes.

## What to Capture

- Code TODOs discovered or created during the session
- File changes made and their rationale
- Bugs found, with reproduction details
- Decisions made and their reasoning
- Items that are blocked, with what they are blocked on
- Open questions that need follow-up

## What NOT to Capture

- Items already written to the journal earlier in the session
- Trivial actions (reading a file, running a passing lint check)
- Speculative ideas that were discussed but explicitly discarded

## Compaction Suggestions

- After loading a project, if the legacy `journal.md` exceeds 500 lines, suggest running `/pensare compact` to age out old entries and reduce context size.
- After a note write, if the target file exceeds 200 lines, suggest compaction for that file.

## Mid-Session KB Demand-Loading

When the conversation shifts to a topic that matches the title or key entities of a knowledge base file listed in the project manifest, re-read the manifest and demand-load the matching KB file. This ensures relevant context is available without loading the entire KB upfront.
