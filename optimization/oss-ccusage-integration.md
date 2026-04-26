# OSS ccusage Integration Plan

**Date:** 2026-04-26
**Status:** Plan
**Goal:** Integrate token tracking and cost optimization into the open-source Pensare plugin, leveraging ccusage (https://github.com/ryoppippi/ccusage) as a reference and optional companion tool.

---

## Background

### ccusage

ccusage is the most mature open-source tool for Claude Code token tracking. It is distributed as an npm package (`npx ccusage`) and works by parsing the JSONL session files that Claude Code writes to `~/.claude/projects/`.

**What it does:**
- Parses JSONL session files for `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`
- Computes dollar costs using current Anthropic pricing tables (per-model)
- Outputs formatted tables to the terminal
- Supports `--json` flag for machine-readable output
- Groups usage by session, model, and date

**What it does NOT do:**
- No per-command attribution (cannot tell you that `/pensare sync` cost 44K tokens)
- No workflow-aware recommendations (cannot suggest incremental sync or lite mode)
- No dashboards or visualizations (terminal tables only)
- No trend analysis or comparisons across time periods

### Pensare's advantage

Pensare already tracks per-command metadata in `metrics.jsonl`. Each command logs its name, project, timestamp, mode, and self-reported token estimates. By correlating these timestamps with the raw JSONL session data that ccusage parses, Pensare can provide attribution that no other tool offers: "your /pensare sync cost 44K tokens, and source X was unchanged 5 of 7 days."

---

## Option A: Shell Out to ccusage

Call `npx ccusage --json` from the metrics command and parse its output.

### How it works

```python
import subprocess, json

result = subprocess.run(
    ["npx", "ccusage", "--json"],
    capture_output=True, text=True, timeout=30
)
sessions = json.loads(result.stdout)
```

### Pros
- Zero parsing code to maintain; ccusage handles all JSONL format changes
- Stays current with Anthropic pricing automatically (ccusage updates its tables)
- Community-maintained edge case handling (malformed lines, encoding issues)

### Cons
- Requires Node.js and npm installed (not all Python-focused users have this)
- Cold start: `npx ccusage` downloads the package on first run (~5-10 seconds)
- Output format is ccusage's choice; breaking changes in their JSON schema affect Pensare
- Adds a runtime dependency to an otherwise self-contained plugin
- Cannot filter by project directory or time range without post-processing
- ccusage may not be available in CI/CD or headless environments

### Verdict: Not recommended as primary path

---

## Option B: Self-Contained JSONL Parsing

Parse Claude Code's session files directly. The format is well-documented and stable.

### How it works

Claude Code writes session data to `~/.claude/projects/*/sessions/*/` as JSONL files. Each line is a JSON object representing a conversation turn. The relevant fields for token tracking are in the `usage` object within assistant responses:

```json
{
  "type": "assistant",
  "message": { ... },
  "usage": {
    "input_tokens": 12400,
    "output_tokens": 1800,
    "cache_read_input_tokens": 8000,
    "cache_creation_input_tokens": 2200
  },
  "model": "claude-sonnet-4-20250514",
  "timestamp": "2026-04-26T14:30:00.000Z"
}
```

The parsing logic is approximately 100 lines of Python:

1. Walk `~/.claude/projects/` for JSONL files modified in the target date range
2. For each file, read lines and parse JSON
3. Extract `usage` fields from assistant-type messages
4. Sum tokens by model, session, and time window
5. Apply Anthropic pricing (hardcoded table, easy to update)

### Pricing table (as of April 2026)

```python
PRICING = {
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_create": 3.75},
    "claude-opus-4":   {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_create": 18.75},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_create": 1.00},
}
# Prices per million tokens
```

### Pros
- No external dependencies; works anywhere Python runs
- Full control over filtering (by project, date range, time window)
- Can correlate with pensare's metrics.jsonl timestamps for per-command attribution
- Portable: works on macOS, Linux, Windows, CI/CD, headless environments
- ~100 lines of straightforward code

### Cons
- Must update pricing table manually when Anthropic changes prices
- Must handle JSONL format changes if Claude Code updates its schema (unlikely to be frequent)
- Loses community edge-case handling that ccusage provides

### Verdict: Recommended as primary path

---

## Recommendation: Option B Primary, ccusage Compatibility Layer

**Primary:** Self-contained JSONL parsing (Option B). This is the default path in the metrics command. No dependencies, always works.

**Optional:** If the user has ccusage installed (`which npx` succeeds and `npx ccusage --version` returns), offer a `--ccusage` flag that shells out to ccusage for token data instead of self-parsing. This gives users who already use ccusage a consistent experience and free pricing updates.

The metrics command checks for ccusage availability silently and does NOT prompt for installation. Pensare should never nag about optional tools.

---

## Per-Command Attribution: How It Works

This is Pensare's unique contribution that neither ccusage nor any other tool provides.

### The correlation algorithm

1. **Pensare side:** Each command logs to `metrics.jsonl` with a start timestamp and end timestamp:
   ```json
   {"timestamp": "2026-04-26T14:30:00Z", "end_timestamp": "2026-04-26T14:30:12Z", "command": "sync", ...}
   ```

2. **Session side:** JSONL session files contain assistant messages with timestamps and token counts.

3. **Correlation:** For each metrics.jsonl entry, find all session messages where `start_timestamp <= message.timestamp <= end_timestamp`. Sum their token counts. This gives per-command actual token usage.

4. **Fallback:** If no session messages fall within the command's time window (timing skew, missing data), use the self-reported estimate from metrics.jsonl.

### What this enables

- "Your /pensare sync cost 44,300 tokens yesterday"
- "Note commands average 18K tokens when reviewing >30 messages, but only 8K in lite mode"
- "Sync compression (the LLM summarization step) accounts for 72% of sync cost"
- "Source X returned identical content on 5 of 7 sync runs"

---

## The `/pensare metrics` Command for OSS

### Default view: 7-day summary dashboard

```
## Token Usage — my-project (last 7 days)

  Total tokens:     842,000  ($2.87)
  Daily average:    120,286  ($0.41)
  Commands run:     47

  Breakdown by command:
    sync          312,000  (37%)  ████████████████░░░░░░░░  7 runs
    note          198,000  (24%)  ██████████░░░░░░░░░░░░░░  18 runs
    load          112,000  (13%)  ███████░░░░░░░░░░░░░░░░░  7 runs
    compact        89,000  (11%)  █████░░░░░░░░░░░░░░░░░░░  1 run
    checkpoint     78,000   (9%)  █████░░░░░░░░░░░░░░░░░░░  7 runs
    publish        42,000   (5%)  ███░░░░░░░░░░░░░░░░░░░░░  2 runs
    other          11,000   (1%)  █░░░░░░░░░░░░░░░░░░░░░░░  5 runs

  Trend:  this week 842K  vs  last week 920K  (-8.5%)

  Recommendations:
    1. SYNC is 37% of your budget. Sources returned identical content 71% of the time.
       -> Enable incremental sync with content hashing. Est. savings: ~150K/week.
    2. NOTE reviews avg 32 messages per run.
       -> Truncate to last 15 messages or switch to lite mode. Est. savings: ~80K/week.
```

### Subcommands

| Flag | Purpose |
|------|---------|
| (none) | Summary dashboard (above) |
| `--detail <command>` | Per-run table for a specific command, component breakdown |
| `--compare` | Standard vs lite mode comparison with projected savings |
| `--sources` | Per-source cost breakdown for sync (which source costs the most) |

### Recommendations engine

10 trigger-based suggestions, computed locally from metrics.jsonl:

| ID | Trigger Condition | Recommendation |
|----|-------------------|----------------|
| R1 | Sync sources return identical content >50% of runs | "Enable incremental sync (content hashing)" |
| R2 | Note reviews >30 messages on average | "Truncate to last 15 messages or use lite mode" |
| R3 | Compact processes >100 entries at once | "Run compact more frequently (weekly) for smaller batches" |
| R4 | Daily token usage >200K | "Consider lite mode — projected savings: {N}%" |
| R5 | Load takes >10 seconds | "Context files are large ({N} lines). Consider splitting." |
| R6 | Checkpoint fires >3x/day with <2 items each | "Reduce checkpoint frequency" |
| R7 | Sync fetches >5 sources but <3 change | "Incremental sync would save ~{N}K/week" |
| R8 | User runs load then sync every session | "Sync auto-loads. Skip separate load — saves ~{N}K/day" |
| R9 | KB files >150 lines after compact | "KB files oversized. Next compact will split them." |
| R10 | Standard mode but daily usage <50K | "Already efficient. Standard mode is fine." |

---

## Lite Mode (Same as Internal Version)

Lite mode is a per-project setting in `sources.json`:

```json
{
  "project_name": "my-project",
  "mode": "lite"
}
```

### Behavioral changes

| Command | Standard | Lite | Savings |
|---------|----------|------|---------|
| `load` | Full context + 2 weeks journal + KB topics | Current week journal + context titles only | ~40-50% |
| `note` | Review entire conversation | Review last 10 messages, terse entry (3-5 lines) | ~50-60% |
| `checkpoint` | Scan entire conversation | Scan last 10 messages, TODOs/decisions only | ~50-60% |
| `sync` | Fetch + LLM compression | Fetch + minimal formatting (no LLM summarization) | ~60-70% |
| `compact` | Full distillation | Simpler prompt, topic-organize only | ~50-60% |
| `publish` | Read all sources, polished | Journal + plan only, terse | ~30-40% |

### Projected daily savings

| Mode | Daily tokens | Daily cost (Sonnet) |
|------|-------------|-------------------|
| Standard | ~160K | ~$0.55 |
| Lite | ~78K | ~$0.27 |
| Savings | ~82K (51%) | ~$0.28 |

---

## Implementation Phases

### Phase 1: Telemetry Foundation (2-3 hours)

Add metrics logging to all commands and create the basic metrics dashboard.

**New files:**
- `commands/metrics.md` — The metrics command (~120 lines)

**Modified files (add ~5 lines each for metrics append):**
- `commands/sync.md`
- `commands/note.md`
- `commands/checkpoint.md`
- `commands/load.md`
- `commands/compact.md`
- `commands/publish.md`
- `commands/setup.md`
- `commands/join.md`

**Data files (auto-created at runtime):**
- `~/.claude/contexts/{project}/metrics.jsonl`

### Phase 2: JSONL Session Parsing (2-3 hours)

Implement self-contained JSONL parsing for actual token counts from Claude Code session files.

**Logic added to `commands/metrics.md`:**
- Walk `~/.claude/projects/` for session JSONL files
- Parse token fields from assistant messages
- Correlate with metrics.jsonl timestamps for per-command attribution
- Apply pricing table

### Phase 3: Lite Mode (4-6 hours)

Add `mode` field to sources.json and mode-aware branching in each command.

**Modified files:**
- All command files (mode-conditional behavior)
- `rules/auto-load-context.md` (titles-only in lite mode)
- `rules/context-preservation.md` (fewer triggers in lite mode)

### Phase 4: Recommendations Engine (3-4 hours)

Add the 10 trigger-based recommendations and `--detail`, `--compare`, `--sources` subcommands.

**Modified files:**
- `commands/metrics.md` — Add analysis logic, subcommand routing, recommendation evaluation

### Phase 5: ccusage Compatibility (1-2 hours)

Add optional `--ccusage` flag that shells out to ccusage for token data.

**Modified files:**
- `commands/metrics.md` — Add ccusage detection and fallback path

---

## File Changes Summary

| File | Phase | Change |
|------|-------|--------|
| `commands/metrics.md` | 1-5 | New file, iteratively expanded |
| `commands/sync.md` | 1, 3 | Add metrics append + lite mode branch |
| `commands/note.md` | 1, 3 | Add metrics append + truncated review |
| `commands/checkpoint.md` | 1, 3 | Add metrics append + truncated scan |
| `commands/load.md` | 1, 3 | Add metrics append + titles-only |
| `commands/compact.md` | 1, 3 | Add metrics append + simpler prompt |
| `commands/publish.md` | 1, 3 | Add metrics append + terse mode |
| `commands/setup.md` | 1 | Add metrics append |
| `commands/join.md` | 1 | Add metrics append |
| `rules/auto-load-context.md` | 3 | Lite mode branch |
| `rules/context-preservation.md` | 3 | Lite mode trigger subset |
| `sources.json` (schema) | 3 | Add `mode` and `telemetry` fields |

---

## ccusage Output Format (Reference)

For compatibility, here is ccusage's `--json` output structure:

```json
[
  {
    "date": "2026-04-26",
    "model": "claude-sonnet-4-20250514",
    "input_tokens": 124000,
    "output_tokens": 18000,
    "cache_read_input_tokens": 80000,
    "cache_creation_input_tokens": 22000,
    "cost": 0.87
  }
]
```

Pensare's metrics command should be able to produce a compatible output format with `--json` so users can pipe into other tools or dashboards.

---

## Open Questions

1. **Pricing update mechanism.** The self-contained parser hardcodes Anthropic pricing. Should Pensare fetch current pricing from a URL on first run each day? Or is manual updates in the command file acceptable?

2. **Cross-project aggregation.** Current design is per-project. Should `--all` aggregate metrics across all projects in `~/.claude/contexts/`?

3. **Historical rollups.** Should the metrics command periodically compact old metrics.jsonl entries into weekly summaries to keep the file manageable? Or rely on the 90-day retention window?

4. **ccusage format evolution.** If ccusage changes its `--json` format, the compatibility layer breaks. Pin to a known version or detect format dynamically?
