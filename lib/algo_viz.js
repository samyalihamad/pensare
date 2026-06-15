/* algo-viz — dependency-free step visualizer (code-sync debugger + layered SVG tree).
 *
 * renderAlgoViz(data, mount): renders into `mount` (an element).
 *   data = { title, start, steps:[{label, action, current|null,
 *            queue:[url], visited:[url], discovered:[url], filtered:[url], line?:int}],
 *            code?:[string] }
 * Graph: a node's parent is the `current` of the step where it first appears in
 * `discovered`; root = `start`. If `code` is present, a synced pseudocode pane is
 * shown and exactly ONE line is highlighted per step (step.line, else inferred).
 *
 * Bundled by the Lambda /doc renderer and reused by standalone viz pages, so it is
 * intentionally framework-free and self-contained.
 */
(function (global) {
  "use strict";

  function shortUrl(u, start) {
    if (!u) return "";
    if (u === start) return start;
    var i = u.indexOf("/");
    return i === -1 ? u : u.slice(i);
  }

  // BFS line inference against the standard pseudocode we ship (used when a step
  // omits `line`). 0:seen 1:queue=deque 2:while 3:popleft 4:for 5:filter 6:skip 7:add 8:append
  function inferLine(step, i, n) {
    if (i === 0) return 1;
    if (step.current == null) return i === n - 1 ? 2 : 1;
    if ((step.discovered || []).length) return 8;
    if ((step.filtered || []).length) return 5;
    return 3;
  }

  function buildTree(data) {
    var steps = data.steps;
    // `start` is optional in the data — infer it from the first step (seed).
    var start = data.start;
    if (!start && steps.length) {
      var s0 = steps[0];
      start = (s0.queue && s0.queue[0]) || (s0.visited && s0.visited[0]) || s0.current;
    }
    var parent = {}; parent[start] = null;
    // primary edges: a node's parent is the `current` of the step that discovered it
    steps.forEach(function (s) {
      (s.discovered || []).forEach(function (u) {
        if (u && !(u in parent)) parent[u] = (s.current != null ? s.current : start);
      });
    });
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

  function renderAlgoViz(data, mount) {
    var steps = data.steps, n = steps.length, tree = buildTree(data);
    var nodeList = Object.keys(tree.nodes).map(function (k) { return tree.nodes[k]; });

    // ---- SVG geometry ----
    var COLW = 150, ROWH = 86, PAD = 34, R = 11;
    var W = tree.width * COLW + PAD * 2, H = (tree.maxDepth + 1) * ROWH + PAD * 2 - (ROWH - 50);
    function px(node) { return PAD + node.x * COLW + COLW / 2; }
    function py(node) { return PAD + node.depth * ROWH; }
    function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }

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

    var hasCode = Array.isArray(data.code) && data.code.length;
    var codeHtml = hasCode ? '<div class="av-code"><ol>' +
      data.code.map(function (ln) { return "<li>" + esc(ln) + "</li>"; }).join("") + "</ol></div>" : "";

    mount.className = (mount.className || "").replace(/\bav\b/, "").trim() + " av";
    mount.innerHTML =
      '<div class="av-title">' + esc(data.title || "Algorithm") + "</div>" +
      '<div class="av-body">' + codeHtml +
        '<div class="av-main">' +
          '<div class="av-tree"><svg viewBox="0 0 ' + W + ' ' + H + '" ' +
            'style="max-width:' + W + 'px;max-height:' + H + 'px" preserveAspectRatio="xMidYMid meet">' +
            edgeSvg + nodeSvg + "</svg></div>" +
          '<div class="av-queue-wrap"><div class="av-row-label">Queue (FIFO)</div>' +
            '<div class="av-queue"></div></div>' +
          '<div class="av-meta"><span class="av-stat">visited <b class="av-vcount">0</b></span>' +
            '<div class="av-chips av-disc"></div><div class="av-chips av-filt"></div></div>' +
        "</div>" +
      "</div>" +
      '<div class="av-narr"></div>' +
      '<div class="av-ctrls">' +
        '<button class="av-btn av-prev">‹ Prev</button>' +
        '<button class="av-btn av-play">▶ Play</button>' +
        '<button class="av-btn av-next">Next ›</button>' +
        '<button class="av-btn av-restart">↻</button>' +
        '<span class="av-prog"></span><div class="av-dots"></div>' +
      "</div>";

    var q = function (s) { return mount.querySelector(s); };
    var dotsWrap = q(".av-dots");
    for (var d = 0; d < n; d++) {
      var b = document.createElement("button");
      b.className = "av-dot"; b.dataset.i = d;
      b.addEventListener("click", function (e) { go(+e.target.dataset.i); });
      dotsWrap.appendChild(b);
    }

    var idx = 0, timer = null;
    function setState(node, cls) {
      var g = mount.querySelector('.av-node[data-url="' + (window.CSS && CSS.escape ? CSS.escape(node) : node.replace(/"/g, '\\"')) + '"]');
      if (g) g.setAttribute("class", "av-node " + cls);
    }
    function render(i) {
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
      // controls
      q(".av-prog").textContent = "Step " + (i + 1) + " / " + n;
      mount.querySelectorAll(".av-dot").forEach(function (dot, di) { dot.classList.toggle("on", di === i); });
      q(".av-prev").disabled = i === 0;
      q(".av-next").disabled = i === n - 1;
    }
    function go(i) { idx = Math.max(0, Math.min(n - 1, i)); render(idx); if (idx === n - 1) stop(); }
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

    render(0);
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
