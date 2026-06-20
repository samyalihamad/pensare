# Algorithm Visualizations (`algo-viz`)

Pensare can render **interactive, step-by-step algorithm visualizations** inside any
project markdown doc. They show up automatically wherever a doc is opened through the
hosted board's `/doc` route (the "Explanation ↗" / "Flashcards ↗" links on kanban
cards), and the same renderer powers standalone HTML demos.

The style is a combined **code-sync debugger + layered SVG tree**: a pseudocode pane
on the left (one line highlighted per step), a graph/tree on the right, a FIFO queue
strip, discovered/filtered chips, a narration bar, and play/step controls.

## How to add a visualization to a doc

Put a fenced code block with the language `algo-viz` containing a JSON object. That's
it — no redeploy, no code change. When the doc is served via `/doc` the block becomes
a live widget; if the JSON is malformed it safely falls back to a normal code block.

````markdown
## BFS Step-by-Step Visualization

```algo-viz
{
  "title": "BFS Web Crawler — news.yahoo.com",
  "start": "news.yahoo.com",
  "code": ["seen = {start}", "queue = deque([start])", "while queue:", "..."],
  "steps": [
    {"label": "Initialize", "current": null,
     "action": "Seed the queue and mark the start visited.",
     "queue": ["news.yahoo.com"], "visited": ["news.yahoo.com"],
     "discovered": [], "filtered": []},
    {"label": "Visit root", "current": "news.yahoo.com",
     "action": "Dequeue the root; enqueue same-host links, filter the rest.",
     "queue": ["news.yahoo.com/finance", "news.yahoo.com/sports"],
     "visited": ["news.yahoo.com", "news.yahoo.com/finance", "news.yahoo.com/sports"],
     "discovered": ["news.yahoo.com/finance", "news.yahoo.com/sports"],
     "filtered": ["cnn.com (off-host)"]}
  ]
}
```
````

## Two layouts: `kind`

Set the top-level `kind` field to pick the layout:

- `"tree"` (default — omit `kind` and you get this): the layered BFS/DFS/traversal tree
  documented below. Frontier = the `queue` strip.
- `"array"`: a row of index boxes with moving pointers and an optional window — for
  sliding-window, two-pointers, binary-search, fast/slow, in-place partition. See
  [Array layout](#array-layout-kindarray) below.

## Schema (tree)

Top level:

| Field | Required | Meaning |
|-------|----------|---------|
| `title` | yes | Header shown above the widget |
| `steps` | yes | Ordered list of step objects (below) |
| `start` | recommended | The root/seed node. **If omitted it is inferred** from the first step's `queue[0]` / `visited[0]` / `current` — but always set it explicitly to be safe. |
| `code` | optional | Array of pseudocode lines. If present, the code-sync pane is shown. |
| `edges` | optional | Explicit structure as `[[parent, child], ...]`. **Use this for traversals.** It decouples the tree *shape* from *visit order*, so in-/post-order (where a parent is output after its children) still draws the real tree. When present, steps only drive coloring, not structure. |
| `frontierLabel` | optional | Relabels the frontier strip (default `"Queue (FIFO)"`). Use `"Stack (LIFO)"` for DFS, `"Output order →"` for traversals, etc. |

Each `steps[i]`:

| Field | Meaning |
|-------|---------|
| `label` | Short step name (e.g. "Visit /finance") |
| `action` | One-sentence narration of what happened |
| `current` | The node being processed this step, or `null` (e.g. init / done) |
| `queue` | The FIFO queue **state after this step** — rendered front→back, must be exact |
| `visited` | The visited/seen set state after this step |
| `discovered` | New nodes found this step (green chips) |
| `filtered` | Links rejected this step — off-host, already-visited, etc. (red chips). These may be human-readable strings like `"cnn.com (off-host)"`, not just URLs. |
| `line` | optional 0-based index into `code` to highlight this step. If omitted, a single line is **inferred** for BFS. |

### How the graph is built

The widget reconstructs a tree from the steps: **a node's parent is the `current` of
the step in which it first appears in `discovered`**; the root is `start`. Depth = BFS
layer. Any node that appears in `visited`/`queue`/`current` but was never `discovered`
is attached to the root rather than dropped. So you only describe steps — the tree is
derived. (Cross-links that revisit a node are handled as *state*, not as extra edges.)

### Code-line highlighting

Exactly **one** line is highlighted per step (this was a deliberate UX choice — multiple
highlights are hard to track). Set `steps[i].line` explicitly for full control. If you
omit it and `code` is the standard BFS pseudocode, the renderer infers: init → the
`queue = deque` line; a step with `discovered` → the `queue.append` (enqueue) line; a
step with only `filtered` → the filter line; a leaf visit → the `popleft` line; the
final step → the `while queue:` line.

## Array layout (`kind:"array"`)

For pointer/window algorithms over a linear array. The view is a fixed row of value boxes
(drawn once); each step redraws an overlay with the window shading, a bracket+note, and the
named pointer carets.

````markdown
```algo-viz
{
  "kind": "array",
  "title": "Two Pointers — two-sum on a sorted array",
  "array": [1, 3, 4, 5, 7, 10, 11, 15],
  "code": ["L = 0; R = len(arr) - 1", "while L < R:", "..."],
  "steps": [
    {"label": "Start", "action": "L at the smallest, R at the largest.",
     "pointers": {"L": 0, "R": 7}, "note": "target=9", "line": 0},
    {"label": "Found", "action": "4 + 5 = 9.",
     "pointers": {"L": 2, "R": 3}, "marked": [2, 3], "note": "4 + 5 = 9 ✓", "line": 3}
  ]
}
```
````

Top level: `kind:"array"` (required), `title`, `array` (the values, drawn as boxes), `code`
(optional, but for arrays a step's `line` must be set **explicitly** — there is no inference).

Each `steps[i]`:

| Field | Meaning |
|-------|---------|
| `label`, `action` | step name + one-sentence narration (same as tree) |
| `pointers` | object `{name: index}` — a labelled caret under each cell. Names get stable colors; multiple pointers on one cell stack. Use `L`/`R`, `i`/`j`, `lo`/`mid`/`hi`, `slow`/`fast`. |
| `window` | optional `[a, b]` inclusive — shades cells a..b and draws a bracket. Use `[0, -1]` (or any `b < a`) for an empty window. |
| `note` | optional label shown on the window bracket (or centered if no window) — e.g. a running sum / current window string. |
| `marked` | optional `[idx, ...]` — individually highlighted result cells (green), e.g. the found pair. |
| `line` | optional 0-based index into `code` to highlight. Required for highlighting in array mode (no inference). |

Indices are clamped to the array bounds, so an off-by-one in the data degrades gracefully
rather than throwing.

## Authoring correct step data — simulate, don't hand-write

The `queue`/`visited` state must be exactly right at every step or the viz misleads.
**Generate the trace by actually running the algorithm**, don't hand-author it. Example
BFS generator (this is how `coding-prep/problems/anthropic/web-crawler.md` was built):

```python
from collections import deque

def bfs_trace(root, children, extra_filtered):
    steps = [{"label": "Initialize", "current": None,
              "action": "Seed the queue and mark the start visited.",
              "queue": [root], "visited": [root], "discovered": [], "filtered": []}]
    seen, q = [root], deque([root])
    while q:
        u = q.popleft()
        disc = [c for c in children.get(u, []) if c not in seen]
        for c in disc:
            seen.append(c); q.append(c)
        steps.append({"label": f"Visit {u}", "current": u,
                      "action": "...", "queue": list(q), "visited": list(seen),
                      "discovered": disc, "filtered": extra_filtered.get(u, [])})
    steps.append({"label": "Done", "current": None, "action": "Queue empty.",
                  "queue": [], "visited": list(seen), "discovered": [], "filtered": []})
    return steps
```

## Implementation

- `lib/algo_viz.js` — the dependency-free renderer (`renderAlgoViz(data, mountEl)` plus
  an auto-boot that mounts every `[data-algo-viz]` element on the page). Pure vanilla
  JS + SVG; no D3/CDN, so it works offline and inside the secret-gated `/doc` pages.
- `lib/algo_viz.css` — styles (dark theme matching the docs; full-bleed width; the tree
  SVG is capped to its natural size so small graphs don't upscale).
- `lib/lambda_handler.py` — `_md_to_html()` turns ` ```algo-viz ` blocks into a mount
  div + a `<script type="application/json">` data block, and injects the CSS/JS **only
  when** a doc actually contains a viz.
- `deploy/lambda-build.sh` — bundles `algo_viz.js` / `algo_viz.css` flat into the Lambda
  zip alongside the `.py` files (the handler reads them from next to itself).

**Changing the renderer** (visual tweaks, new layout modes) → edit `lib/algo_viz.{js,css}`,
then rebuild + redeploy:

```bash
export PATH="$HOME/.local/bin:$PATH"          # aws CLI shim, see memory/aws-cli-shim
bash deploy/lambda-build.sh
aws lambda update-function-code --function-name pensare-kanban --region us-east-1 \
  --zip-file fileb://deploy/kanban-lambda.zip
```

**Adding/fixing viz content** (a doc's `algo-viz` block) → it's just data in the doc, so
write the doc to S3 (`lib/storage.py ... write`) — no redeploy needed.

## Standalone demos

The same component renders a self-contained HTML page (open via `file://`). Build one by
wrapping the data + `algo_viz.css` + `algo_viz.js`:

```html
<style>{algo_viz.css}</style>
<div data-algo-viz="d-data"></div>
<script type="application/json" id="d-data">{ ...the algo-viz JSON... }</script>
<script>{algo_viz.js}</script>
```

Reference demos live in `~/Downloads/pensare-viz-demos/` (4 style explorations +
`demo-5-combined-webcrawler.html`, the shipped style).

## Notes & gotchas

- The `/doc` markdown renderer supports headings, code fences, inline code/bold/links,
  lists, and `algo-viz` — **not** markdown tables. Use lists/headings in docs.
- Keep node identifiers short or hierarchical; the widget displays a URL by stripping
  the host (`news.yahoo.com/finance` → `/finance`) with the full value on hover.
- Two layouts ship today: the top-down **tree** (`kind:"tree"`, default) and the **array**
  row (`kind:"array"`, see above). A linear-structure (deque/linked-list) mode would be the
  next extension — add a `kind` value and a matching layout in `algo_viz.js`.
