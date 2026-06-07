"use client";

import { useEffect, useState } from "react";
import MarkdownContent from "./MarkdownContent";
import AlgoViz from "@/components/viz/AlgoViz";

type ContextData = {
  title: string;
  markdown: string;
  vizData: unknown | null;
};

export default function LessonViewer({
  project,
  path,
}: {
  project: string;
  path: string;
}) {
  const [data, setData] = useState<ContextData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        if (!path) {
          throw new Error("Missing ?path= query param.");
        }
        const res = await fetch(
          `/api/context?project=${encodeURIComponent(project)}&path=${encodeURIComponent(path)}`,
          { cache: "no-store" },
        );
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.error ?? `HTTP ${res.status}`);
        }
        const json = (await res.json()) as ContextData;
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [project, path]);

  if (error) {
    return (
      <div className="p-6 text-accent-red">
        <button
          onClick={() => history.back()}
          className="text-fg-muted hover:text-fg mb-4"
        >
          ← Back
        </button>
        <h1 className="text-xl mb-2">Failed to load lesson</h1>
        <p className="font-mono text-sm">{error}</p>
      </div>
    );
  }

  if (!data) {
    return <div className="p-6 text-fg-muted">Loading…</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <button
        onClick={() => history.back()}
        className="text-fg-muted hover:text-fg mb-4 text-sm"
      >
        ← Back
      </button>
      <h1 className="text-2xl font-semibold mb-4 text-fg">{data.title}</h1>
      <MarkdownContent markdown={data.markdown} />
      {data.vizData ? (
        <div className="mt-8">
          <AlgoViz data={data.vizData} />
        </div>
      ) : null}
    </div>
  );
}
