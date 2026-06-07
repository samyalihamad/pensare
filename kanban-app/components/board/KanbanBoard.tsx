"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import KanbanColumn from "./KanbanColumn";
import FlashcardModal from "./FlashcardModal";

export type Item = {
  id: string;
  title: string;
  status: string;
  priority?: string;
  category?: string;
  company?: string;
  leetcode_num?: string;
  leetcode_slug?: string;
  flashcard_topic?: string;
  created?: string;
  updated?: string;
  _ref_label?: string;
  _ref_path?: string;
};

export type BoardData = {
  project: string;
  columns: string[];
  board: Record<string, Item[]>;
  total: number;
};

const STATUS_BY_COLUMN: Record<string, string> = {
  Backlog: "backlog",
  "In Progress": "in-progress",
  Review: "review",
  Blocked: "blocked",
  Done: "done",
};

export function statusForColumn(column: string): string {
  return STATUS_BY_COLUMN[column] ?? column.toLowerCase().replace(/\s+/g, "-");
}

export default function KanbanBoard({ project }: { project: string }) {
  const [data, setData] = useState<BoardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [flashcardTopic, setFlashcardTopic] = useState<string | null>(null);
  const columnRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const fetchBoard = useCallback(async () => {
    try {
      const res = await fetch(`/api/board?project=${encodeURIComponent(project)}`, {
        cache: "no-store",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${res.status}`);
      }
      const json = (await res.json()) as BoardData;
      setData(json);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project]);

  useEffect(() => {
    void fetchBoard();
    const id = setInterval(() => void fetchBoard(), 30_000);
    return () => clearInterval(id);
  }, [fetchBoard]);

  const setColumnRef = useCallback((column: string) => {
    return (el: HTMLDivElement | null) => {
      columnRefs.current[column] = el;
    };
  }, []);

  const moveItem = useCallback(
    async (item: Item, targetColumn: string) => {
      if (!data) return;
      const targetStatus = statusForColumn(targetColumn);
      if (item.status === targetStatus) return;

      // Optimistic update
      const next: BoardData = {
        ...data,
        board: Object.fromEntries(
          Object.entries(data.board).map(([col, items]) => [
            col,
            items.filter((it) => it.id !== item.id),
          ]),
        ) as Record<string, Item[]>,
      };
      next.board[targetColumn] = [
        { ...item, status: targetStatus },
        ...(next.board[targetColumn] ?? []),
      ];
      setData(next);

      try {
        const res = await fetch(
          `/api/items/${encodeURIComponent(item.id)}?project=${encodeURIComponent(project)}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: targetStatus }),
          },
        );
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.error ?? `HTTP ${res.status}`);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        // Roll back by refetching.
        void fetchBoard();
        return;
      }
      void fetchBoard();
    },
    [data, project, fetchBoard],
  );

  const getColumnAtPoint = useCallback((clientX: number, clientY: number): string | null => {
    for (const [col, el] of Object.entries(columnRefs.current)) {
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (
        clientX >= r.left &&
        clientX <= r.right &&
        clientY >= r.top &&
        clientY <= r.bottom
      ) {
        return col;
      }
    }
    return null;
  }, []);

  if (error && !data) {
    return (
      <div className="p-6 text-accent-red">
        <h1 className="text-xl mb-2">Failed to load board</h1>
        <p className="font-mono text-sm">{error}</p>
      </div>
    );
  }

  if (!data) {
    return <div className="p-6 text-fg-muted">Loading…</div>;
  }

  return (
    <div className="flex flex-col h-screen">
      {flashcardTopic && (
        <FlashcardModal
          project={project}
          topic={flashcardTopic}
          onClose={() => setFlashcardTopic(null)}
        />
      )}
      <header className="px-5 py-3 border-b border-border-muted flex items-center justify-between bg-[#161b22]">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold">Pensare</h1>
          <span className="text-fg-muted text-sm">— {data.project}</span>
          <span className="text-fg-dim text-xs">({data.total} items)</span>
        </div>
        <div className="text-xs text-fg-muted">
          {error ? (
            <span className="text-accent-red">error: {error}</span>
          ) : (
            <span>updated {lastUpdated.toLocaleTimeString()}</span>
          )}
        </div>
      </header>
      <div className="flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex gap-4 p-4 h-full min-w-max">
          {data.columns.map((col) => (
            <KanbanColumn
              key={col}
              column={col}
              items={data.board[col] ?? []}
              project={data.project}
              setRef={setColumnRef(col)}
              onDragEnd={(item, point) => {
                const target = getColumnAtPoint(point.x, point.y);
                if (target && target !== col) void moveItem(item, target);
              }}
              onFlashcards={setFlashcardTopic}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
