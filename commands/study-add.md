---
allowed-tools: Read, Write, Edit, Glob, Bash(date *), Bash(ls *), Bash(mkdir *)
argument-hint: [sub-category]
description: Add flashcards to a study sub-category (paste your own or auto-generate), or create a new sub-category
---

## Study Project Data Structure

See `/pensare:study-quiz` for the full layout. In short, a study project lives in
`~/.claude/contexts/{project}/` with one kebab-case folder per sub-category, each
containing a `flashcards.md` deck and a `notes.md`.

**Flashcard format** appended to `flashcards.md` (one blank line between cards):

```
Q: <question>
A: <answer>
```

# Study Add — Add or Generate Flashcards

Arguments: $ARGUMENTS

#### Step 1: Resolve Project

Use the study project loaded in the current session. Do not ask for a project name.
Read `~/.claude/contexts/{project}/sources.json`.

- If no project is loaded: "No project loaded. Run `/pensare load <keyword>` first, or `/pensare:setup` to create a study project."
- If `sources.json` lacks `"template": "study"`, warn once but continue.

List existing sub-category directories (subdirs containing `flashcards.md`; ignore
`journal/`, `kb/`, `kanban/`).

#### Step 2: Resolve Sub-Category

Determine the target sub-category:
- If `$ARGUMENTS` matches an existing sub-category (case-insensitive, spaces↔hyphens, partial) → use it.
- If `$ARGUMENTS` is given but matches nothing → ask: "No sub-category '{arg}' yet. Create it? (y/n)". If yes, treat it as a **new** sub-category (Step 3a).
- If `$ARGUMENTS` is empty → show the existing sub-categories and ask: "Which sub-category? (pick one, or type a new name to create it.)"

**Step 3a — Creating a new sub-category:** convert the name to kebab-case, then:
```bash
mkdir -p ~/.claude/contexts/{project}/{kebab-name}/
```
Write `{kebab-name}/flashcards.md` and `{kebab-name}/notes.md` using the same templates
the Study template uses (header comment in `flashcards.md`; notes scaffold in `notes.md`).
Add a row for it to the `## Sub-Categories` table in `Overview.md`.

#### Step 3: Choose How to Add Cards

Ask:
> "How do you want to add cards to **{sub-category}**?
> 1. **Paste** — you give me Q/A pairs (or just questions and I'll draft answers)
> 2. **Generate from a topic** — I create cards on a topic you name
> 3. **Generate from notes** — I turn `{sub-category}/notes.md` into cards
> Enter 1, 2, or 3:"

**Option 1 — Paste:** Ask the user to paste cards. Accept flexible input:
`Q: ... / A: ...` blocks, `question | answer` lines, or bare questions (draft concise
answers yourself and show them for approval before saving). Show the parsed cards and
confirm before writing.

**Option 2 — Generate from a topic:** Ask "Which topic, and how many cards? (e.g., 'eigenvalues, 10')".
Generate that many clear, exam-quality flashcards: one focused fact/skill per card,
concise answers. Show them and ask the user to approve / edit / drop any.

**Option 3 — Generate from notes:** Read `{sub-category}/notes.md`. If it's empty,
tell the user and fall back to Option 2. Otherwise generate flashcards that cover the
key points in the notes. Show them for approval.

#### Step 4: Append and Confirm

Append the approved cards to `~/.claude/contexts/{project}/{sub-category}/flashcards.md`,
each as a `Q:`/`A:` block separated by a blank line. Do not duplicate a card whose
question already exists in the file (skip near-duplicates and mention how many you skipped).

Recount the total cards in that deck and update the **Cards** count for this
sub-category in the `## Sub-Categories` table of `Overview.md`.

Confirm:
> "Added **{k}** cards to **{sub-category}** (deck now has {total}).
> Quiz them: `/pensare:study-quiz {sub-category}`"
