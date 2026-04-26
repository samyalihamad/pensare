---
globs: ["**/*"]
alwaysApply: true
---

# Auto-Load Pensare Context

## Session Start Behavior

At the beginning of every session, check whether any pensare projects exist under `~/.claude/contexts/`. If projects are found and the user's first message relates to a known project (by name, topic, or working directory), automatically load that project's context. This is equivalent to invoking `/pensare load`.

## Loading Rules

- Only load if the user's first message is relevant to a project. Do not load for generic questions like "hello" or "how do I use git".
- If multiple projects exist, select the one most relevant to the user's message. If ambiguous, ask the user which project to load.
- If `working_directory` is set in the project's `sources.json`, treat that path as the project root for all file operations in that session.

## Freshness Check

After loading a project, check the `last_sync` timestamp in `sources.json`. If the last sync was more than 24 hours ago, suggest that the user run `/pensare sync` to refresh external sources.

- Do NOT auto-sync. Syncing can be expensive (external fetches, API calls) and should only happen when the user explicitly requests it.
- Frame the suggestion as informational: "Your project context was last synced X hours ago. You may want to run `/pensare sync` to pull the latest."

## Constraints

- Never skip the load step for status or briefing questions ("what's the status?", "catch me up", "what's next?"), even if context appears to already be loaded from a prior turn or compacted summary.
- If context was compacted mid-session, always re-load before answering any project-related question.
