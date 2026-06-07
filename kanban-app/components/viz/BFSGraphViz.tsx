"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import StepControls from "./StepControls";

export type GraphNode = {
  id: string;
  label?: string;
  host?: string;
  filtered?: boolean;
};

export type GraphEdge = {
  source: string;
  target: string;
};

export type BFSStep = {
  label: string;
  queue: string[];
  visited: string[];
  current: string | null;
  discovered: string[];
  filtered: string[];
  active_edges: [string, string][];
  action: string;
};

export type BFSGraphData = {
  type: "bfs-graph";
  title?: string;
  graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
  steps: BFSStep[];
};

type NodeDatum = GraphNode & d3.SimulationNodeDatum;
type EdgeDatum = d3.SimulationLinkDatum<NodeDatum> & {
  source: NodeDatum;
  target: NodeDatum;
  key: string;
};

const STATE_FILL: Record<string, string> = {
  default: "#21262d",
  queue: "#1c2d3d",
  visited: "#0d2818",
  current: "#2d2208",
  filtered: "#1c1c1c",
};

const STATE_STROKE: Record<string, string> = {
  default: "#30363d",
  queue: "#388bfd",
  visited: "#3fb950",
  current: "#d29922",
  filtered: "#484f58",
};

const STATE_LABEL: Record<string, string> = {
  default: "#7d8590",
  queue: "#58a6ff",
  visited: "#7ee787",
  current: "#ffd166",
  filtered: "#6e7681",
};

const WIDTH = 720;
const HEIGHT = 380;
const NODE_R = 26;

export default function BFSGraphViz({ data }: { data: BFSGraphData }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [stepIdx, setStepIdx] = useState(0);
  const step = data.steps[stepIdx];
  const totalSteps = data.steps.length;

  // Build stable data once. Use deep-cloned arrays so d3 mutates copies.
  const { nodes, edges } = useMemo(() => {
    const nodeById = new Map<string, NodeDatum>();
    const nodes: NodeDatum[] = data.graph.nodes.map((n) => {
      const datum: NodeDatum = { ...n };
      nodeById.set(n.id, datum);
      return datum;
    });
    const edges: EdgeDatum[] = data.graph.edges.map((e) => {
      const s = nodeById.get(e.source);
      const t = nodeById.get(e.target);
      if (!s || !t) {
        throw new Error(`Edge references unknown node: ${e.source} → ${e.target}`);
      }
      return { source: s, target: t, key: `${e.source}->${e.target}` };
    });
    return { nodes, edges };
  }, [data]);

  // Run the force simulation once at mount; positions are then frozen.
  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    // Marker for arrowheads.
    svg
      .append("defs")
      .append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", NODE_R + 8)
      .attr("refY", 0)
      .attr("markerWidth", 7)
      .attr("markerHeight", 7)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#484f58");

    svg
      .append("defs")
      .append("marker")
      .attr("id", "arrow-active")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", NODE_R + 8)
      .attr("refY", 0)
      .attr("markerWidth", 8)
      .attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#388bfd");

    const linkGroup = svg.append("g").attr("class", "links");
    const nodeGroup = svg.append("g").attr("class", "nodes");

    const link = linkGroup
      .selectAll<SVGLineElement, EdgeDatum>("line")
      .data(edges, (d) => d.key)
      .join("line")
      .attr("stroke", "#30363d")
      .attr("stroke-width", 1.4)
      .attr("marker-end", "url(#arrow)")
      .attr("data-key", (d) => d.key);

    const node = nodeGroup
      .selectAll<SVGGElement, NodeDatum>("g.node")
      .data(nodes, (d) => d.id)
      .join("g")
      .attr("class", "node")
      .attr("data-id", (d) => d.id);

    node
      .append("circle")
      .attr("r", NODE_R)
      .attr("fill", STATE_FILL.default)
      .attr("stroke", STATE_STROKE.default)
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", STATE_LABEL.default)
      .attr("font-family", "ui-monospace, SFMono-Regular, Menlo, monospace")
      .attr("font-size", "11px")
      .text((d) => d.label ?? d.id);

    // Run simulation off-screen, then freeze.
    const sim = d3
      .forceSimulation<NodeDatum>(nodes)
      .force(
        "link",
        d3
          .forceLink<NodeDatum, EdgeDatum>(edges)
          .id((d) => d.id)
          .distance(120)
          .strength(0.8),
      )
      .force("charge", d3.forceManyBody<NodeDatum>().strength(-380))
      .force("center", d3.forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("collide", d3.forceCollide<NodeDatum>(NODE_R + 6))
      .stop();

    for (let i = 0; i < 300; i++) sim.tick();

    // Clamp nodes inside the viewport.
    for (const n of nodes) {
      n.x = Math.max(NODE_R + 4, Math.min(WIDTH - NODE_R - 4, n.x ?? WIDTH / 2));
      n.y = Math.max(NODE_R + 4, Math.min(HEIGHT - NODE_R - 4, n.y ?? HEIGHT / 2));
      n.fx = n.x;
      n.fy = n.y;
    }

    node.attr("transform", (d) => `translate(${d.x ?? 0}, ${d.y ?? 0})`);
    link
      .attr("x1", (d) => d.source.x ?? 0)
      .attr("y1", (d) => d.source.y ?? 0)
      .attr("x2", (d) => d.target.x ?? 0)
      .attr("y2", (d) => d.target.y ?? 0);
  }, [nodes, edges]);

  // Re-color nodes/edges in response to the active step.
  useEffect(() => {
    if (!svgRef.current || !step) return;
    const svg = d3.select(svgRef.current);

    const stateById = new Map<string, string>();
    for (const n of nodes) {
      stateById.set(n.id, n.filtered ? "filtered" : "default");
    }
    for (const id of step.queue) stateById.set(id, "queue");
    for (const id of step.visited) stateById.set(id, "visited");
    for (const id of step.filtered) stateById.set(id, "filtered");
    if (step.current) stateById.set(step.current, "current");

    const activeKeys = new Set(step.active_edges.map(([s, t]) => `${s}->${t}`));

    const DUR = 400;
    const ease = d3.easeCubicOut;

    svg
      .selectAll<SVGCircleElement, NodeDatum>("g.node circle")
      .transition()
      .duration(DUR)
      .ease(ease)
      .attr("fill", function (this: SVGCircleElement) {
        const id = (this.parentNode as SVGGElement).getAttribute("data-id") ?? "";
        const state = stateById.get(id) ?? "default";
        return STATE_FILL[state];
      })
      .attr("stroke", function (this: SVGCircleElement) {
        const id = (this.parentNode as SVGGElement).getAttribute("data-id") ?? "";
        const state = stateById.get(id) ?? "default";
        return STATE_STROKE[state];
      })
      .attr("stroke-dasharray", function (this: SVGCircleElement) {
        const id = (this.parentNode as SVGGElement).getAttribute("data-id") ?? "";
        const state = stateById.get(id) ?? "default";
        return state === "filtered" ? "4 3" : "none";
      });

    svg
      .selectAll<SVGTextElement, NodeDatum>("g.node text")
      .transition()
      .duration(DUR)
      .ease(ease)
      .attr("fill", function (this: SVGTextElement) {
        const id = (this.parentNode as SVGGElement).getAttribute("data-id") ?? "";
        const state = stateById.get(id) ?? "default";
        return STATE_LABEL[state];
      });

    // Pulse the current node.
    svg.selectAll<SVGCircleElement, NodeDatum>("g.node circle").interrupt("pulse");
    svg.selectAll<SVGCircleElement, NodeDatum>("g.node circle").attr("r", NODE_R);
    if (step.current) {
      const sel = svg.select<SVGGElement>(`g.node[data-id="${cssEscape(step.current)}"]`);
      const pulse = (): void => {
        sel
          .select<SVGCircleElement>("circle")
          .transition("pulse")
          .duration(800)
          .attr("r", NODE_R + 3)
          .transition("pulse")
          .duration(800)
          .attr("r", NODE_R)
          .on("end", pulse);
      };
      pulse();
    }

    svg
      .selectAll<SVGLineElement, EdgeDatum>("g.links line")
      .transition()
      .duration(DUR)
      .ease(ease)
      .attr("stroke", function (this: SVGLineElement) {
        const key = this.getAttribute("data-key") ?? "";
        return activeKeys.has(key) ? "#388bfd" : "#30363d";
      })
      .attr("stroke-width", function (this: SVGLineElement) {
        const key = this.getAttribute("data-key") ?? "";
        return activeKeys.has(key) ? 2.4 : 1.4;
      })
      .attr("marker-end", function (this: SVGLineElement) {
        const key = this.getAttribute("data-key") ?? "";
        return activeKeys.has(key) ? "url(#arrow-active)" : "url(#arrow)";
      });
  }, [step, nodes]);

  if (!step) return null;

  return (
    <div className="rounded border border-border-muted bg-[#161b22] p-4">
      {data.title && (
        <div className="text-sm text-fg-muted mb-2 font-mono">{data.title}</div>
      )}
      <div className="text-sm font-semibold mb-2">{step.label}</div>
      <div className="border border-border-muted rounded bg-[#0d1117] overflow-hidden">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="xMidYMid meet"
          className="w-full h-auto block"
        />
      </div>
      <p className="text-sm text-fg-muted mt-3 leading-relaxed">{step.action}</p>
      <div className="grid grid-cols-2 gap-3 mt-3 text-xs">
        <Pills label="queue" ids={step.queue} color="#388bfd" />
        <Pills label="visited" ids={step.visited} color="#3fb950" />
      </div>
      <StepControls
        step={stepIdx}
        total={totalSteps}
        onPrev={() => setStepIdx((i) => Math.max(0, i - 1))}
        onNext={() => setStepIdx((i) => Math.min(totalSteps - 1, i + 1))}
        onJump={setStepIdx}
      />
    </div>
  );
}

function Pills({ label, ids, color }: { label: string; ids: string[]; color: string }) {
  return (
    <div>
      <div className="text-fg-dim mb-1 uppercase tracking-wide text-[10px]">
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {ids.length === 0 ? (
          <span className="text-fg-dim text-[11px]">(empty)</span>
        ) : (
          ids.map((id) => (
            <span
              key={id}
              className="font-mono text-[11px] px-1.5 py-0.5 rounded border"
              style={{ borderColor: color, color }}
            >
              {id}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

function cssEscape(s: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(s);
  }
  return s.replace(/(["'\\\.#\[\]:])/g, "\\$1");
}
