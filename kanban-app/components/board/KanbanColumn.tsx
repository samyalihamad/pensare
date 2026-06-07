"use client";

import KanbanCard from "./KanbanCard";
import type { Item } from "./KanbanBoard";

export default function KanbanColumn({
  column,
  items,
  project,
  setRef,
  onDragEnd,
  onFlashcards,
}: {
  column: string;
  items: Item[];
  project: string;
  setRef: (el: HTMLDivElement | null) => void;
  onDragEnd: (item: Item, point: { x: number; y: number }) => void;
  onFlashcards?: (topic: string) => void;
}) {
  return (
    <div
      ref={setRef}
      className="w-72 shrink-0 bg-[#161b22] border border-border-muted rounded-md flex flex-col max-h-full"
    >
      <div className="px-3 py-2 border-b border-border-muted flex items-center justify-between">
        <h2 className="text-sm font-semibold text-fg">{column}</h2>
        <span className="text-xs text-fg-dim bg-[#21262d] px-1.5 py-0.5 rounded">
          {items.length}
        </span>
      </div>
      <div className="p-2 overflow-y-auto flex-1 space-y-2">
        {items.map((item) => (
          <KanbanCard
            key={item.id}
            item={item}
            project={project}
            onDragEnd={(point) => onDragEnd(item, point)}
            onFlashcards={onFlashcards}
          />
        ))}
        {items.length === 0 && (
          <div className="text-fg-dim text-xs text-center py-6">empty</div>
        )}
      </div>
    </div>
  );
}
