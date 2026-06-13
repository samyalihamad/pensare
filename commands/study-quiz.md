---
allowed-tools: Read, Write, Edit, Glob, Bash(date *), Bash(ls *)
argument-hint: [sub-category | "all"]
description: Run a flashcard quiz on a sub-category or the whole subject of the loaded study project
---

## Study Project Data Structure

A study project (created by `/pensare:setup` with the **Study** template) lives in
`~/.claude/contexts/{project}/`:

```
{project}/
├── sources.json          # contains "template": "study" and the subject
├── Overview.md           # subject summary + Sub-Categories table + Progress log
├── derivatives/          # one folder per sub-category (kebab-case)
│   ├── flashcards.md     # the deck (Q:/A: pairs)
│   └── notes.md
├── integrals/
│   ├── flashcards.md
│   └── notes.md
└── ...
```

**Flashcard format** inside `flashcards.md` — cards are separated by a blank line:

```
Q: What is the derivative of sin(x)?
A: cos(x)

Q: State the power rule.
A: d/dx[x^n] = n·x^(n-1)
```

An answer may span multiple lines; a card ends at the next blank line that precedes
the next `Q:` (or end of file). Lines inside HTML comments (`<!-- ... -->`) are not cards.

# Study Quiz — Flashcard Quiz

Arguments: $ARGUMENTS

#### Step 1: Resolve Project and Scope

Use the study project already loaded in the current session. Do not ask for a project
name. Read `~/.claude/contexts/{project}/sources.json`.

- If no project is loaded, tell the user: "No project loaded. Run `/pensare load <keyword>` first, or `/pensare:setup` to create a study project."
- If `sources.json` does not have `"template": "study"`, warn: "'{project}' isn't a study project, but I'll look for flashcard folders anyway." Then continue.

List the sub-category directories: every subdirectory of the project that contains a
`flashcards.md` file (ignore `journal/`, `kb/`, `kanban/`).

Determine the **scope**:
- If `$ARGUMENTS` is empty, or is `all` / `full` / `everything` → scope = **whole subject** (all sub-categories).
- Otherwise match `$ARGUMENTS` to a sub-category folder (case-insensitive; tolerate spaces vs hyphens and partial matches). If exactly one matches, scope = that sub-category. If several match, list them and ask which. If none match, show the available sub-categories and ask the user to pick one (or `all`).

#### Step 2: Load the Deck

Read `flashcards.md` from each in-scope sub-category and parse the `Q:`/`A:` pairs
(skip commented-out lines). Tag each card with its sub-category.

- If the in-scope decks have **zero** cards, tell the user:
  > "No flashcards found for {scope}. Add some with `/pensare:study-add {scope}` — I can also auto-generate them for you."
  Then stop.

Report the count: "Found **{N}** cards across {scope}."

#### Step 3: Quiz Options

Ask in one message:
> "Quiz setup —
> • How many questions? (enter for all {N})
> • Order? **random** (default) or **in-order**"

Accept short replies (e.g., "10 random", "all", just enter). Defaults: all cards, random order.

If random, shuffle the chosen cards. If a count smaller than N is given, take that many.

Tell the user how it works:
> "I'll ask one question at a time. Type your answer, or `skip`, `reveal`, or `stop` at any point. Let's go."

#### Step 4: Run the Quiz (one card per turn)

For each selected card, in turn:

1. Present the question only:
   > **Q{i}/{total}** _({sub-category})_
   > {question}

2. Wait for the user's reply. Then:
   - `stop` → end the quiz now and go to Step 5 with the cards answered so far.
   - `skip` → mark the card **skipped** (not counted as right or wrong) and move on.
   - `reveal` → show the answer, mark it **missed**, move on.
   - Otherwise treat the reply as their answer and **grade it semantically**: judge whether it captures the key idea(s) of the stored answer, not an exact string match. Classify as **correct**, **partial**, or **incorrect**.

3. Give immediate feedback:
   > {✓ Correct / ◐ Partially correct / ✗ Not quite}
   > **Answer:** {stored answer}
   > {one-line note on what was missing, only when partial/incorrect}

   Count **correct** as 1 point, **partial** as 0.5, **incorrect**/**missed** as 0.
   Track missed and partial cards (with their sub-category) for the summary.

Keep momentum — do not re-print the whole deck, just the current card.

#### Step 5: Score Summary

Get today's date: `date +%Y-%m-%d`.

Compute the score over graded cards (exclude skipped from the denominator):
`score = round(points) / graded`, plus a percentage.

Present:
> ## Quiz complete — {scope}
> **Score: {points}/{graded}  ({percent}%)**
>
> **Review these:**
> | Sub-Category | Question | Your gap |
> |--------------|----------|----------|
> (one row per missed/partial card; omit the table if none)
>
> {skipped count, if any}

#### Step 6: Record Results

1. **Update Overview.md Progress table.** Read `~/.claude/contexts/{project}/Overview.md`.
   Insert a new row at the top of the `## Progress` table body:
   `| {today} | {scope} | {points}/{graded} ({percent}%) | {missed count} | {short note} |`

   Also refresh the `## Sub-Categories` table for the quizzed sub-categories: set
   **Last Quiz** = {today} and **Best Score** = max(existing, this percent). Recompute
   **Cards** from each `flashcards.md` if the existing count looks stale.

2. **Offer to journal and act on weak spots.** Ask:
   > "Log this to the journal and/or generate extra flashcards for the topics you missed? (journal / generate / both / no)"
   - `journal` or `both` → compose a `/pensare note`-style entry summarizing scope, score, and weak areas, and append it to the project journal (follow the same journaling behavior as `/pensare note`).
   - `generate` or `both` → for each missed sub-category, follow `/pensare:study-add` behavior to generate a few targeted flashcards on the missed questions.
   - `no` → done.

End with a short encouraging line and the exact command to re-quiz the weak area, e.g.
`/pensare:study-quiz {weakest sub-category}`.
