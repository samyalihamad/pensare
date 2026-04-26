---
allowed-tools: Read
description: Show pensare help with commands, data flow, and examples
---

# Help — Pensare Command Reference

Print the following help text:

```
## /pensare — Project Workflow (Latin: "to think")

Manage project context, journal progress, and publish to plans.
Files stored in: ~/.claude/contexts/{project}/ (local) or git-tracked directory with symlink (git mode)

### Commands

  /pensare setup                          Create a new project (TL creates team config)
  /pensare join <team_folder>             Join an existing project (IC onboarding)
  /pensare sync [project]                 Sync sources into context files
  /pensare load <keyword>                 Load context + journal into session
  /pensare note <instruction>             Add a journal entry (Claude composes it)
  /pensare checkpoint                     Auto-save un-journaled session state
  /pensare compact [project]              Compact journal — age entries into knowledge base
  /pensare publish [target]               Preview and push mature content to plan files
  /pensare list                           List all projects and context files
  /pensare help                           Show this help

### Natural Language (just say what you want)

  You don't need to remember command names. Just describe what you
  want — pensare's intent detection recognizes the intent and routes
  to the right command automatically.

  "record what we fixed"
    → note (reviews conversation, composes entry, appends to journal)

  "publish to the plan"
    → publish (previews plan file changes, confirms, writes)

  "record and publish"
    → note then publish (chaining — composes entry, then publishes)

  "pull latest"
    → sync (fetches sources, updates context files, auto-loads)

  "catch me up on auth"
    → load (reads context + journal, presents status briefing)

  "set up a new project"
    → setup (interactive project wizard)

  "join the team project"
    → join (reads shared config, creates local project)

  "what projects do I have?"
    → list (shows all projects with status)

  "save progress"
    → checkpoint (captures un-journaled session state)

  "compact the journal"
    → compact (migrates legacy format, ages hot entries into KB)

### How Data Flows

  EXTERNAL SOURCES (Google Docs, GitHub, Slack, Notion, files, RSS)
       |
       |  /pensare sync
       v
  LOCAL CONTEXT (~/.claude/contexts/{project}/)
  +---------------------------------------------+
  |  Overview.md, Plan.md, ...  <- from sync    |
  |  journal/{week}.md          <- from note    |
  |  kb/*.md                    <- from compact |
  +--------------------+------------------------+
                       |
                       |  /pensare load (reads context + journal)
                       v
  YOUR SESSION
  +---------------------------------------------+
  |  Full picture: synced context + journal     |
  |  ... work, debug, test ...                  |
  |  /pensare note -> appends to journal        |
  |  /pensare checkpoint -> auto-saves state    |
  |  /pensare compact -> ages hot entries -> kb |
  +--------------------+------------------------+
                       |
                       |  /pensare publish (preview -> confirm -> write)
                       v
  SOURCE-CONTROLLED PLAN FILES (your repo)
  +---------------------------------------------+
  |  Only mature, vetted content                |
  +---------------------------------------------+

### Example: A Full Day

  MORNING
    "catch me up on auth"             -> load
    "pull latest"                     -> sync (if context is stale)

  WORKING
    "record the test results"         -> note
    "log the decisions we made"       -> note

  END OF DAY
    "record what we did and push to the plan"
                                      -> note + publish

  WEEKLY
    "compact the journal"             -> compact (if journal growing)

  FIRST TIME
    /pensare setup                    TL: Interactive project wizard
    /pensare setup --template         Templates: workspace or custom
    /pensare join path/to/team/       IC: Join from shared config

### Key Concepts

  Storage modes
    - Local: ~/.claude/contexts/{project}/ (default, single machine)
    - Git: git-tracked directory with symlink from ~/.claude/contexts/ (persists across machines)

  Three-tier journal
    - Hot: journal/{week}.md (rolling ~30 days, full entries grouped by ISO week)
    - Knowledge base: kb/*.md (AI-distilled, topic-partitioned, permanent)
    - Manifest: journal/manifest.json (structured index with one-line summaries)
    - /pensare compact ages expired hot entries into KB files via AI distillation

  Templates
    - Start from workspace or custom templates during setup
    - Templates pre-populate context files, sections, and directory structure

  Natural language routing
    - No slash commands needed — describe what you want in plain English
    - Intent detection recognizes the action and routes to the right command

  Sync sources
    - url: any URL (Google Docs, web pages)
    - file: local files
    - github_pr / github_issue: GitHub PRs and issues (via gh CLI or GitHub MCP)
    - slack: Slack channels (via Slack MCP)
    - notion: Notion pages and databases (via Notion MCP)
    - linear / jira: issue trackers
    - git_log: recent git commits in a directory
    - rss: RSS/Atom feeds
    - mcp: any named MCP tool (generic escape hatch)
```
