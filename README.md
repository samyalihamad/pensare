# Pensare

**Project workflow tool for Claude Code.** Manage context, journal progress, and publish plans across sessions.

*Pensare* is Latin for "to think" -- reflecting the plugin's purpose: giving Claude Code a structured way to think about projects over time, across sessions, and with teams.

---

## The Problem

Claude Code sessions are ephemeral. When a session ends, everything learned -- decisions, investigations, context -- disappears. Teams working on multi-session projects lose continuity. Context gets re-explained. Mistakes get repeated.

Pensare solves this by giving every project two persistent layers:

1. **Local context** (`~/.claude/contexts/{project}/`) -- your working memory. Markdown files that hold everything the current session needs to know.
2. **Source-controlled plans** (in your repo) -- the shared truth. Durable artifacts that survive beyond any single session or developer.

The plugin manages the flow between these layers: syncing external information in, loading context at session start, journaling progress during work, and publishing results to source-controlled files when milestones are reached.

---

## Installation

### From the plugin registry

```bash
claude plugin install pensare
```

### From source

```bash
git clone https://github.com/pensare-claude/pensare.git ~/.claude/plugins/pensare
claude plugin install --local ~/.claude/plugins/pensare
```

---

## Data Flow

```
External Sources --> /sync --> ~/.claude/contexts/{project}/*.md
                                        |  ^
                                  /load |  | /note
                                        v  |
                                  Session (working memory)
                                        |
                                  /compact
                                        |
                                        v
                              journal/ --> kb/ (knowledge base)
                                        |
                                  /publish
                                        |
                                        v
                              Source-controlled plan files
```

Information flows in one direction: from external sources, through local context, into the session, and ultimately out to durable, source-controlled plans. Each command moves data along this pipeline.

---

## Commands

| Command | Description |
|---|---|
| `/pensare setup` | Initialize a new project. Creates the context directory, scaffolds config, and sets up journal structure. Optionally bootstraps from a template (workspace or custom). |
| `/pensare join` | Join an existing project created by a teammate. Reads a shared config file and sets up your local context directory with the same structure and sync sources. |
| `/pensare sync` | Pull fresh data from configured external sources into your local context files. Supports URLs, files, GitHub PRs/issues, Slack, Discord, Notion, Linear, Jira, git logs, RSS feeds, and generic MCP tool output. |
| `/pensare load` | Load all context files for the current project into the session. This is the primary way to restore continuity at the start of a new session. |
| `/pensare note` | Append a timestamped entry to the project journal. Accepts free-form text. Use throughout a session to record decisions, findings, blockers, and progress. |
| `/pensare checkpoint` | Save a snapshot of the current session state -- context files, journal, and any in-progress work -- so it can be restored later. Useful before risky operations or at the end of a work block. |
| `/pensare compact` | Distill the journal into the knowledge base. Summarizes recent journal entries into structured, permanent KB articles. Keeps the journal lean while preserving institutional knowledge. |
| `/pensare publish` | Write finalized content from the knowledge base or journal to source-controlled plan files in your repository. This is how session work becomes durable, shared artifacts. |
| `/pensare list` | List all configured projects, their sync sources, and journal status (entry count, last compaction date, KB article count). |
| `/pensare help` | Show usage information for all commands, or detailed help for a specific command. |

All commands also respond to natural language. You do not need to use slash syntax -- saying "load the project context" or "sync my sources" works the same way.

---

## Sync Sources

The `/pensare sync` command pulls data from external sources into your local context files. Each source is declared in the project config (`config.yaml`) and maps to a context file.

| Source Type | Description | Example |
|---|---|---|
| `url` | Fetch and extract content from a web page or API endpoint | Documentation pages, wiki articles |
| `file` | Copy content from a local file path | Config files, spec documents |
| `github_pr` | Pull title, description, comments, and diff summary from a GitHub PR | Code review context |
| `github_issue` | Pull title, body, labels, and comments from a GitHub issue | Bug reports, feature requests |
| `slack` | Fetch recent messages from a Slack channel or thread | Team discussions, decisions |
| `discord` | Fetch recent messages from a Discord channel | Community discussions |
| `notion` | Pull content from a Notion page or database | Project specs, roadmaps |
| `linear` | Pull issue details from Linear | Sprint tracking, issue context |
| `jira` | Pull issue details from Jira | Enterprise project tracking |
| `git_log` | Extract recent commit messages from a git repository | Change history, release notes |
| `rss` | Fetch recent entries from an RSS or Atom feed | Blog posts, release announcements |
| `generic_mcp` | Call any MCP tool and capture its output | Custom integrations |

Sources are processed in declaration order. Each source writes to a specific context file, which can then be loaded into the session.

---

## Three-Tier Journal System

Pensare uses a three-tier system to manage project knowledge over time:

### Tier 1: Hot Journal (weekly files, 30-day window)

The active working log. Every `/pensare note` appends a timestamped entry to the current week's journal file (`journal/2026-W17.md`). Entries are free-form markdown -- decisions, findings, code snippets, blockers, links. Journal files older than 30 days are candidates for compaction.

### Tier 2: Knowledge Base (AI-distilled, permanent)

When you run `/pensare compact`, the plugin analyzes recent journal entries and distills them into structured KB articles in the `kb/` directory. Each article has a clear title, tags, and content. The KB is the permanent memory of the project -- it survives journal rotation and is the primary source for `/pensare publish`.

### Tier 3: Manifest (structured index)

The `manifest.json` file is a structured index of all KB articles, their tags, creation dates, and relationships. It enables fast lookup and cross-referencing without reading every KB file. The manifest is updated automatically during compaction.

```
journal/
  2026-W15.md          <-- older, compacted into KB
  2026-W16.md          <-- older, compacted into KB
  2026-W17.md          <-- current week, active
kb/
  etc-tenant-setup.md  <-- distilled from journal entries
  allocator-debug.md   <-- distilled from journal entries
  perf-baselines.md    <-- distilled from journal entries
manifest.json          <-- structured index of KB articles
```

---

## Templates

When running `/pensare setup`, you can bootstrap from a template to get a pre-configured project structure:

### workspace

General-purpose project template. Includes context files for overview, decisions, and open questions. Good for feature development, tech debt projects, or explorations.

### custom

Start from a blank config and build your own structure. Useful when your project does not fit the standard templates.

---

## Team Collaboration

Pensare supports team workflows where multiple developers work on the same project across their own Claude Code sessions.

### Setting up a shared project

The tech lead (or project owner) runs `/pensare setup` and commits the generated config file to the repository:

```
repo/
  .pensare/
    config.yaml        <-- shared project config
    plan-files/         <-- source-controlled plans (shared truth)
```

### Joining a shared project

Individual contributors clone the repo and run:

```
/pensare join
```

This reads the shared `config.yaml` and creates the local context directory (`~/.claude/contexts/{project}/`) with the same structure, sync sources, and journal configuration. Each developer's journal and KB are local -- only published plan files are shared through source control.

---

## Storage Modes

### Local (default)

Context files live in `~/.claude/contexts/{project}/`. This is the simplest mode and works for solo developers or projects where persistence beyond the local machine is not needed.

### Git-backed

For projects where you want journal and KB files to persist across machines, Pensare can store them in a git repository. A symlink connects the standard context path to the git-backed directory:

```
~/.claude/contexts/{project}/ --> ~/notes/projects/{project}/
```

The git-backed directory is a regular git repository that you can push and pull independently. This is useful for:

- Preserving context across machine rebuilds or ephemeral dev environments
- Sharing raw context (not just published plans) with teammates
- Auditing the full history of project knowledge evolution

### AWS S3 (cloud-native)

A project's files (journal, KB, context, kanban) live in a private S3 bucket and are read/written directly through a storage helper — reachable from any machine with no git push/pull, and a prerequisite for the **online kanban board**.

```
~/.claude/contexts/{project}/sources.json   <-- thin local stub (names the bucket)
s3://pensare-store-<account>/contexts/{project}/   <-- the real files
```

A one-time `deploy/bootstrap.sh` creates a single shared bucket + Lambda + Function URL; then each new project just needs a prefix and a secret. Choose **AWS S3** in `/pensare setup` (Step 4) and it's provisioned for you. See [deploy/README.md](deploy/README.md) for setup, security, and cost.

**Online kanban board.** When a project uses S3 storage, `/pensare setup` can host its kanban board online: the same drag-and-drop board is served by an AWS Lambda over a private, secret-gated HTTPS URL — no local server. `/pensare:kanban-ui` opens that URL; `/pensare:kanban-add` and `/pensare:kanban-update` write straight to S3 via shared logic, so the online board and your terminal stay in sync.

---

## Project Structure

```
pensare/
  .claude-plugin/
    plugin.json          <-- plugin metadata, hooks, command registration
    manifest.json        <-- dependency manifest (empty for OSS)
  commands/
    setup.md             <-- project creation wizard
    join.md              <-- IC onboarding from shared config
    sync.md              <-- fetch sources, update context
    load.md              <-- read context + journal into session
    note.md              <-- Claude-composed journal entry
    checkpoint.md        <-- auto-save un-journaled state
    compact.md           <-- journal compaction + KB distillation
    publish.md           <-- push to source-controlled plan files
    list.md              <-- show all projects
    help.md              <-- command reference
  hooks/
    inject-rules.sh      <-- SessionStart: injects rules into session
    update-memory.py     <-- PostToolUse: extracts patterns to MEMORY.md
  rules/
    auto-load-context.md     <-- auto-load at session start
    context-preservation.md  <-- auto-checkpoint triggers, KB demand-loading
    intent-detection.md      <-- natural language to command routing
  templates/
    workspace.json       <-- long-lived project template
  LICENSE
  README.md
```

---

## Context Preservation

Pensare includes built-in rules for maintaining context across session boundaries:

- **Auto-checkpoint**: Before context compaction events, Pensare automatically checkpoints the current state so nothing is lost if the compaction produces unexpected results.
- **Auto-load**: The `SessionStart` hook injects a rule reminding the session to load project context before answering questions. This prevents the common failure mode of answering from stale or missing context after a session restart.
- **Memory updates**: The `PostToolUse` hook monitors file writes and edits, updating the project memory index so that future sessions know which files have changed and may need re-reading.

---

## Natural Language Intent Detection

You do not need to memorize slash commands. Pensare detects intent from natural language:

| What you say | What runs |
|---|---|
| "Load the project context" | `/pensare load` |
| "What projects do I have?" | `/pensare list` |
| "Save a note about the API change" | `/pensare note` |
| "Sync my sources" | `/pensare sync` |
| "Publish the results to the plan" | `/pensare publish` |
| "Set up a new project for the migration" | `/pensare setup` |
| "Compact the journal" | `/pensare compact` |

The command definition file (`commands/pensare.md`) includes intent-matching patterns that Claude Code uses to route natural language to the correct command.

---

## Key Design Decisions

### Prompt-driven commands, code-driven hooks

Commands (`commands/pensare.md`) are implemented as prompt files -- markdown documents that instruct Claude Code what to do. This makes them transparent, auditable, and easy to customize. Hooks (`hooks/`) are implemented as shell scripts and Python, because they need to run automatically without Claude's involvement (e.g., injecting rules at session start, updating memory after file edits).

### Local-first, publish-to-share

All working state lives locally. Nothing is shared until you explicitly run `/pensare publish`. This avoids accidental pollution of shared plan files with half-formed thoughts, and gives each developer the freedom to journal and explore without affecting the team.

### Journal compaction instead of deletion

Old journal entries are never deleted -- they are compacted into KB articles. The raw journal files can be kept in an archive if desired, but the distilled KB articles are the canonical long-term memory. This ensures no context is ever truly lost, while keeping the active working set small and fast to load.

### No external dependencies

Pensare has no runtime dependencies beyond Claude Code itself. Sync sources that require API access (Slack, GitHub, Notion, etc.) use adapters that detect available credentials or MCP servers at runtime. If a source is not available, it is skipped with a warning rather than failing the entire sync.

### Convention over configuration

Sensible defaults for everything: 30-day journal window, weekly file rotation, standard context directory path, standard KB format. All of these can be overridden in `config.yaml`, but the defaults work well for most projects.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
