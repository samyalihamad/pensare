"use client";

import BFSGraphViz, { type BFSGraphData } from "./BFSGraphViz";

export default function AlgoViz({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const obj = data as { type?: string };
  if (obj.type === "bfs-graph") {
    return <BFSGraphViz data={data as BFSGraphData} />;
  }
  return (
    <div className="rounded border border-border-muted bg-[#161b22] p-4 text-fg-muted">
      Unknown viz type: {String(obj.type ?? "<missing>")}
    </div>
  );
}
