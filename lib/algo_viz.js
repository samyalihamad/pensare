/* algo-viz — dependency-free step visualizer (code-sync debugger + SVG view).
 *
 * renderAlgoViz(data, mount): renders into `mount` (an element).
 *   Two layouts, selected by `data.kind`:
 *
 *   "tree" (default) — layered BFS/DFS/traversal tree:
 *     data = { kind?, title, start, code?:[string], steps:[{label, action,
 *              current|null, queue:[node], visited:[node], discovered:[node],
 *              filtered:[node], line?:int}] }
 *     A node's parent is the `current` of the step where it first appears in
 *     `discovered`; root = `start`.
 *
 *   "array" — row of index boxes with moving pointers + an optional window:
 *     data = { kind:"array", title, array:[val,...], code?:[string],
 *              steps:[{label, action, pointers:{name:idx,...}, window?:[a,b],
 *                      note?:string, marked?:[idx], line?:int}] }
 *     `pointers` are named carets under cells (L/R/i/j/slow/fast/lo/mid/hi…);
 *     `window` shades cells a..b inclusive and draws a bracket labelled `note`;
 *     `marked` shades individual result cells.
 *
 * If `code` is present a synced pseudocode pane is shown and exactly ONE line is
 * highlighted per step (step.line, else inferred for the tree path).
 *
 * Bundled by the Lambda /doc renderer and reused by standalone viz pages, so it is
 * intentionally framework-free and self-contained.
 */
(function (global) {
  "use strict";

  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }

  function shortUrl(u, start) {
    if (!u) return "";
    if (u === start) return start;
    var i = u.indexOf("/");
    return i === -1 ? u : u.slice(i);
  }

  // ── Shared playback chrome ──────────────────────────────────────────────────
  // Both views build the same controls/dots markup, then hand a per-step paint
  // function here. setupPlayback owns idx/timer, the progress label, dot state,
  // prev/next disabled state, and keyboard/auto-play wiring.
  function setupPlayback(mount, n, renderStep) {
    var q = function (s) { return mount.querySelector(s); };
    var dotsWrap = q(".av-dots");
    for (var d = 0; d < n; d++) {
      var b = document.createElement("button");
      b.className = "av-dot"; b.dataset.i = d;
      b.addEventListener("click", function (e) { stop(); go(+e.target.dataset.i); });
      dotsWrap.appendChild(b);
    }
    var idx = 0, timer = null;
    function paint(i) {
      renderStep(i);
      q(".av-prog").textContent = "Step " + (i + 1) + " / " + n;
      mount.querySelectorAll(".av-dot").forEach(function (dot, di) { dot.classList.toggle("on", di === i); });
      q(".av-prev").disabled = i === 0;
      q(".av-next").disabled = i === n - 1;
    }
    function go(i) { idx = Math.max(0, Math.min(n - 1, i)); paint(idx); if (idx === n - 1) stop(); }
    function stop() { if (timer) { clearInterval(timer); timer = null; q(".av-play").textContent = "▶ Play"; } }
    function play() {
      if (timer) return stop();
      if (idx === n - 1) go(0);
      q(".av-play").textContent = "❚❚ Pause";
      timer = setInterval(function () { if (idx >= n - 1) return stop(); go(idx + 1); }, 1100);
    }
    q(".av-prev").addEventListener("click", function () { stop(); go(idx - 1); });
    q(".av-next").addEventListener("click", function () { stop(); go(idx + 1); });
    q(".av-restart").addEventListener("click", function () { stop(); go(0); });
    q(".av-play").addEventListener("click", play);
    document.addEventListener("keydown", function (e) {
      if (/INPUT|TEXTAREA/.test((e.target && e.target.tagName) || "")) return;
      var r = mount.getBoundingClientRect();
      if (r.bottom < 0 || r.top > (window.innerHeight || 9999)) return; // only the on-screen viz
      if (e.key === "ArrowLeft") { stop(); go(idx - 1); e.preventDefault(); }
      else if (e.key === "ArrowRight") { stop(); go(idx + 1); e.preventDefault(); }
      else if (e.key === " ") { play(); e.preventDefault(); }
    });
    paint(0);
  }

  function codePane(data) {
    var hasCode = Array.isArray(data.code) && data.code.length;
    return hasCode ? '<div class="av-code"><ol>' +
      data.code.map(function (ln) { return "<li>" + esc(ln) + "</li>"; }).join("") + "</ol></div>" : "";
  }
  function ctrlsHtml() {
    return '<div class="av-ctrls">' +
      '<button class="av-btn av-prev">‹ Prev</button>' +
      '<button class="av-btn av-play">▶ Play</button>' +
      '<button class="av-btn av-next">Next ›</button>' +
      '<button class="av-btn av-restart">↻</button>' +
      '<span class="av-prog"></span><div class="av-dots"></div>' +
    "</div>";
  }

  // ── Tree view ───────────────────────────────────────────────────────────────
  // BFS line inference against the standard pseudocode we ship (used when a step
  // omits `line`). 0:seen 1:queue=deque 2:while 3:popleft 4:for 5:filter 6:skip 7:add 8:append
  // A visit that finds children highlights the `for` line (mid-loop) rather than the
  // final `append` — otherwise nearly every step parks on the last line and looks stuck.
  function inferLine(step, i, n) {
    if (i === 0) return 1;
    if (step.current == null) return i === n - 1 ? 2 : 1;
    if ((step.discovered || []).length) return 4;
    if ((step.filtered || []).length) return 5;
    return 3;
  }

  function buildTree(data) {
    var steps = data.steps;
    var start = data.start;
    var parent = {};
    if (Array.isArray(data.edges) && data.edges.length) {
      // explicit structure: [[parent, child], ...]. Decouples the tree shape from
      // visit order, so in-/post-order traversals (parent visited after children)
      // still draw the real tree. root = `start`, else the node that is never a child.
      data.edges.forEach(function (e) { parent[e[1]] = e[0]; });
      data.edges.forEach(function (e) { if (!(e[0] in parent)) parent[e[0]] = null; });
      if (!start) {
        var childSet = {}; data.edges.forEach(function (e) { childSet[e[1]] = 1; });
        Object.keys(parent).forEach(function (u) { if (!childSet[u]) start = start || u; });
      }
      parent[start] = null;
    } else {
      // inferred structure: a node's parent is the `current` of the step that discovered it.
      if (!start && steps.length) {
        var s0 = steps[0];
        start = (s0.queue && s0.queue[0]) || (s0.visited && s0.visited[0]) || s0.current;
      }
      parent[start] = null;
      steps.forEach(function (s) {
        (s.discovered || []).forEach(function (u) {
          if (u && !(u in parent)) parent[u] = (s.current != null ? s.current : start);
        });
      });
    }
    // never orphan: any url that ever appears but wasn't discovered attaches to root
    steps.forEach(function (s) {
      ["visited", "queue"].forEach(function (f) {
        (s[f] || []).forEach(function (u) { if (u && !(u in parent)) parent[u] = start; });
      });
      if (s.current && !(s.current in parent)) parent[s.current] = start;
    });

    var nodes = {}; // url -> node
    Object.keys(parent).forEach(function (u) { nodes[u] = { url: u, parent: parent[u], children: [], depth: 0 }; });
    Object.keys(nodes).forEach(function (u) {
      var p = nodes[u].parent;
      if (p != null && nodes[p]) nodes[p].children.push(nodes[u]);
    });
    function depth(n) { var d = 0, c = n, g = 0; while (c.parent != null && nodes[c.parent] && g++ < 999) { d++; c = nodes[c.parent]; } return d; }
    Object.keys(nodes).forEach(function (u) { nodes[u].depth = depth(nodes[u]); });

    // top-down layout: assign leaf slots L->R, center parents over children
    var slot = 0, maxDepth = 0;
    (function assign(n) {
      maxDepth = Math.max(maxDepth, n.depth);
      if (!n.children.length) { n.x = slot++; return; }
      n.children.forEach(assign);
      n.x = (n.children[0].x + n.children[n.children.length - 1].x) / 2;
    })(nodes[start]);
    // safety: position any node the recursion didn't reach
    Object.keys(nodes).forEach(function (u) { if (nodes[u].x == null) nodes[u].x = slot++; });
    return { nodes: nodes, root: start, width: Math.max(1, slot), maxDepth: maxDepth };
  }

  function renderTreeView(data, mount) {
    var steps = data.steps, n = steps.length, tree = buildTree(data);
    var nodeList = Object.keys(tree.nodes).map(function (k) { return tree.nodes[k]; });

    // ---- SVG geometry ----
    var COLW = 150, ROWH = 86, PAD = 34, R = 11;
    var W = tree.width * COLW + PAD * 2, H = (tree.maxDepth + 1) * ROWH + PAD * 2 - (ROWH - 50);
    function px(node) { return PAD + node.x * COLW + COLW / 2; }
    function py(node) { return PAD + node.depth * ROWH; }

    var edgeSvg = "", nodeSvg = "";
    nodeList.forEach(function (nd) {
      if (nd.parent != null && tree.nodes[nd.parent]) {
        var p = tree.nodes[nd.parent];
        var x1 = px(p), y1 = py(p) + R, x2 = px(nd), y2 = py(nd) - R, my = (y1 + y2) / 2;
        edgeSvg += '<path class="av-edge" data-to="' + esc(nd.url) + '" d="M' + x1 + ',' + y1 +
          ' C' + x1 + ',' + my + ' ' + x2 + ',' + my + ' ' + x2 + ',' + y2 + '"/>';
      }
    });
    nodeList.forEach(function (nd) {
      var x = px(nd), y = py(nd), label = shortUrl(nd.url, tree.root);
      nodeSvg += '<g class="av-node unvisited" data-url="' + esc(nd.url) + '"><title>' + esc(nd.url) + '</title>' +
        '<circle class="av-pulse" cx="' + x + '" cy="' + y + '" r="' + R + '"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + R + '"/>' +
        '<text x="' + x + '" y="' + (y + R + 13) + '" text-anchor="middle">' + esc(label) + '</text></g>';
    });

    mount.innerHTML =
      '<div class="av-title">' + esc(data.title || "Algorithm") + "</div>" +
      '<div class="av-body">' + codePane(data) +
        '<div class="av-main">' +
          '<div class="av-tree"><svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'style="max-width:' + W + 'px;max-height:' + H + 'px" preserveAspectRatio="xMidYMid meet">' +
            edgeSvg + nodeSvg + "</svg></div>" +
          '<div class="av-queue-wrap"><div class="av-row-label">' + esc(data.frontierLabel || "Queue (FIFO)") + "</div>" +
            '<div class="av-queue"></div></div>' +
          '<div class="av-meta"><span class="av-stat">visited <b class="av-vcount">0</b></span>' +
            '<div class="av-chips av-disc"></div><div class="av-chips av-filt"></div></div>' +
        "</div>" +
      "</div>" +
      '<div class="av-narr"></div>' + ctrlsHtml();

    var q = function (s) { return mount.querySelector(s); };
    var hasCode = Array.isArray(data.code) && data.code.length;
    function setState(node, cls) {
      var g = mount.querySelector('.av-node[data-url="' + (window.CSS && CSS.escape ? CSS.escape(node) : node.replace(/"/g, '\\"')) + '"]');
      if (g) g.setAttribute("class", "av-node " + cls);
    }
    function renderStep(i) {
      var s = steps[i];
      var queued = {}; (s.queue || []).forEach(function (u) { queued[u] = 1; });
      var visited = {}; (s.visited || []).forEach(function (u) { visited[u] = 1; });
      nodeList.forEach(function (nd) {
        var u = nd.url, cls = "unvisited";
        if (u === s.current) cls = "current";
        else if (queued[u]) cls = "queued";
        else if (visited[u]) cls = "done";
        setState(u, cls);
      });
      // edges leading to a queued/done/current node light up
      mount.querySelectorAll(".av-edge").forEach(function (e) {
        var to = e.getAttribute("data-to");
        e.classList.toggle("on", !!(queued[to] || visited[to] || to === s.current));
      });
      // queue
      var qWrap = q(".av-queue"), qq = s.queue || [];
      if (!qq.length) qWrap.innerHTML = '<span class="av-empty">empty</span>';
      else qWrap.innerHTML = qq.map(function (u, j) {
        var cap = j === 0 ? '<span class="av-cap">front▸</span>' : (j === qq.length - 1 ? '<span class="av-cap">◂back</span>' : "");
        return (j === 0 ? cap : "") + '<span class="av-qbox' + (j === 0 ? " front" : "") + '" title="' + esc(u) + '">' +
          esc(shortUrl(u, tree.root)) + "</span>" + (j === qq.length - 1 && j !== 0 ? cap : "");
      }).join("");
      // meta
      q(".av-vcount").textContent = (s.visited || []).length;
      q(".av-disc").innerHTML = (s.discovered || []).map(function (u) {
        return '<span class="av-chip disc" title="' + esc(u) + '">+ ' + esc(shortUrl(u, tree.root)) + "</span>"; }).join("");
      q(".av-filt").innerHTML = (s.filtered || []).map(function (u) {
        return '<span class="av-chip filt" title="' + esc(u) + '">' + esc(u) + "</span>"; }).join("");
      // narration
      q(".av-narr").innerHTML = "<b>" + esc(s.label || ("Step " + (i + 1))) + "</b> — " + esc(s.action || "");
      // code highlight (single line)
      if (hasCode) {
        var line = (typeof s.line === "number") ? s.line : inferLine(s, i, n);
        mount.querySelectorAll(".av-code li").forEach(function (li, li_i) { li.classList.toggle("active", li_i === line); });
      }
    }
    setupPlayback(mount, n, renderStep);
  }

  // ── Array view ──────────────────────────────────────────────────────────────
  // Row of index boxes; per step we re-draw a small SVG layer with the window
  // shading, the bracket+note, and the named pointer carets. The array itself is
  // static so this stays simple and correct (no per-cell diffing).
  var PTR_COLORS = ["#58a6ff", "#f85149", "#3fb950", "#d29922", "#bc8cff", "#39c5cf"];

  function renderArrayView(data, mount) {
    var steps = data.steps, n = steps.length, arr = data.array || [];
    var len = arr.length;
    // assign a stable color to each pointer name across all steps
    var ptrOrder = [], seen = {};
    steps.forEach(function (s) {
      Object.keys(s.pointers || {}).forEach(function (name) {
        if (!(name in seen)) { seen[name] = ptrOrder.length; ptrOrder.push(name); }
      });
    });
    function ptrColor(name) { return PTR_COLORS[seen[name] % PTR_COLORS.length]; }

    // geometry — clean vertical bands, top→bottom, so nothing overlaps:
    //   [note]  [boxes]  [index #]  [pointer carets]  [pointer labels, stacked]
    var BOX = 56, GAP = 8, PADX = 24;
    var NOTEY = 16, ARRY = 30, ARRH = 48;
    var IDXY = ARRY + ARRH + 14;                       // index numbers under each box
    var CARETTIP = ARRY + ARRH + 24, CARETBASE = CARETTIP + 9;  // caret points up at its column
    var LABELY0 = CARETBASE + 13, LABELSTEP = 15;      // pointer names below the carets
    var maxPtrRows = 1;
    steps.forEach(function (s) {
      var perCell = {};
      Object.keys(s.pointers || {}).forEach(function (name) { var i = s.pointers[name]; perCell[i] = (perCell[i] || 0) + 1; });
      Object.keys(perCell).forEach(function (k) { maxPtrRows = Math.max(maxPtrRows, perCell[k]); });
    });
    var W = PADX * 2 + len * (BOX + GAP) - GAP;
    var H = LABELY0 + (maxPtrRows - 1) * LABELSTEP + 12;
    function lx(i) { return PADX + i * (BOX + GAP); }
    function cx(i) { return lx(i) + BOX / 2; }

    // static cells (values + index labels) — drawn once
    var cellsSvg = "";
    for (var i = 0; i < len; i++) {
      cellsSvg += '<g class="av-cell">' +
        '<rect x="' + lx(i) + '" y="' + ARRY + '" width="' + BOX + '" height="' + ARRH + '" rx="7"/>' +
        '<text class="av-cellval" x="' + cx(i) + '" y="' + (ARRY + ARRH / 2 + 6) + '" text-anchor="middle">' + esc(arr[i]) + "</text>" +
        '<text class="av-idx" x="' + cx(i) + '" y="' + IDXY + '" text-anchor="middle">' + i + "</text>" +
      "</g>";
    }

    mount.innerHTML =
      '<div class="av-title">' + esc(data.title || "Algorithm") + "</div>" +
      '<div class="av-body">' + codePane(data) +
        '<div class="av-main">' +
          '<div class="av-arraywrap"><svg class="av-arraysvg" viewBox="0 0 ' + W + ' ' + H + '" ' +
            'style="max-width:' + W + 'px" preserveAspectRatio="xMidYMid meet">' +
            '<g class="av-dyn-bg"></g>' + cellsSvg + '<g class="av-dyn-fg"></g></svg></div>' +
          '<div class="av-ptrlegend"></div>' +
        "</div>" +
      "</div>" +
      '<div class="av-narr"></div>' + ctrlsHtml();

    var q = function (s) { return mount.querySelector(s); };
    var hasCode = Array.isArray(data.code) && data.code.length;
    var bgG = q(".av-dyn-bg"), fgG = q(".av-dyn-fg");

    // static legend of pointer names -> colors
    q(".av-ptrlegend").innerHTML = ptrOrder.map(function (name) {
      return '<span class="av-leg"><i style="background:' + ptrColor(name) + '"></i>' + esc(name) + "</span>";
    }).join("");

    function clampIdx(v) { return Math.max(0, Math.min(len - 1, v)); }
    function renderStep(k) {
      var s = steps[k];
      // background: window shading + individual marked cells
      var bg = "";
      var win = s.window;
      if (win && win.length === 2) {
        var a = clampIdx(win[0]), b = clampIdx(win[1]);
        if (b >= a) bg += '<rect class="av-winfill" x="' + (lx(a) - 3) + '" y="' + (ARRY - 3) +
          '" width="' + (lx(b) + BOX - lx(a) + 6) + '" height="' + (ARRH + 6) + '" rx="9"/>';
      }
      (s.marked || []).forEach(function (mi) {
        var c = clampIdx(mi);
        bg += '<rect class="av-markfill" x="' + lx(c) + '" y="' + ARRY + '" width="' + BOX + '" height="' + ARRH + '" rx="7"/>';
      });
      bgG.innerHTML = bg;

      // foreground: the note sits ABOVE the array (its own band) so it never
      // collides with the pointer carets/labels below; then carets + stacked labels.
      var fg = "";
      if (s.note) {
        var nx = W / 2;
        if (win && win.length === 2) { var wa = clampIdx(win[0]), wb = clampIdx(win[1]); if (wb >= wa) nx = (cx(wa) + cx(wb)) / 2; }
        // keep the centered note inside the viewBox — near an edge it would clip
        // (e.g. a window at index 0 chopped "win='a'…" to "='a'…").
        var halfW = String(s.note).length * 3.7, lo = 4 + halfW, hi = W - 4 - halfW;
        nx = lo <= hi ? Math.max(lo, Math.min(hi, nx)) : W / 2;
        fg += '<text class="av-note" x="' + nx + '" y="' + NOTEY + '" text-anchor="middle">' + esc(s.note) + "</text>";
      }
      // pointers: group by cell so multiple at one index stack downward
      var byCell = {};
      Object.keys(s.pointers || {}).forEach(function (name) {
        var idx = clampIdx(s.pointers[name]);
        (byCell[idx] = byCell[idx] || []).push(name);
      });
      Object.keys(byCell).forEach(function (idx) {
        var x = cx(+idx), top = byCell[idx];
        // caret pointing up at the cell, colored by the first pointer on this cell
        fg += '<path class="av-caret" d="M' + (x - 6) + ',' + CARETBASE + ' L' + (x + 6) + ',' + CARETBASE + ' L' + x + ',' + CARETTIP + ' Z" fill="' + ptrColor(top[0]) + '"/>';
        top.forEach(function (name, r) {
          fg += '<text class="av-ptrlabel" x="' + x + '" y="' + (LABELY0 + r * LABELSTEP) + '" text-anchor="middle" fill="' + ptrColor(name) + '">' + esc(name) + "</text>";
        });
      });
      fgG.innerHTML = fg;

      // narration
      q(".av-narr").innerHTML = "<b>" + esc(s.label || ("Step " + (k + 1))) + "</b> — " + esc(s.action || "");
      // code highlight (single line, explicit only for arrays)
      if (hasCode && typeof s.line === "number") {
        mount.querySelectorAll(".av-code li").forEach(function (li, li_i) { li.classList.toggle("active", li_i === s.line); });
      }
    }
    setupPlayback(mount, n, renderStep);
  }

  // ── Entry ───────────────────────────────────────────────────────────────────
  function renderAlgoViz(data, mount) {
    mount.className = (mount.className || "").replace(/\bav\b/, "").trim() + " av";
    if (data && data.kind === "array") return renderArrayView(data, mount);
    return renderTreeView(data, mount);
  }

  function boot() {
    var mounts = document.querySelectorAll("[data-algo-viz]");
    mounts.forEach(function (m) {
      var src = document.getElementById(m.getAttribute("data-algo-viz"));
      if (!src) return;
      try { renderAlgoViz(JSON.parse(src.textContent), m); }
      catch (err) { m.innerHTML = '<pre style="color:#f85149">algo-viz error: ' + (err && err.message) + "</pre>"; }
    });
  }

  global.renderAlgoViz = renderAlgoViz;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})(window);
