"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import type { Item } from "./KanbanBoard";

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-[#3f1418] text-[#ff7b72] border-[#5e1a20]",
  medium: "bg-[#3a2c0e] text-[#ffd166] border-[#5d4514]",
  low: "bg-[#0f2818] text-[#7ee787] border-[#163b22]",
};

export default function KanbanCard({
  item,
  project,
  onDragEnd,
  onFlashcards,
}: {
  item: Item;
  project: string;
  onDragEnd: (point: { x: number; y: number }) => void;
  onFlashcards?: (topic: string) => void;
}) {
  const priorityClass =
    PRIORITY_STYLES[(item.priority ?? "medium").toLowerCase()] ??
    PRIORITY_STYLES.medium;

  const lessonHref = item._ref_path
    ? `/lesson?project=${encodeURIComponent(project)}&path=${encodeURIComponent(item._ref_path)}`
    : null;

  const leetcodeHref =
    item.leetcode_slug && item.leetcode_slug.length > 0
      ? `https://leetcode.com/problems/${item.leetcode_slug}/`
      : null;

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragElastic={0.04}
      dragSnapToOrigin
      whileDrag={{ scale: 1.03, zIndex: 50, cursor: "grabbing" }}
      onDragEnd={(_, info) => {
        onDragEnd({ x: info.point.x, y: info.point.y });
      }}
      className="bg-[#0d1117] border border-border rounded-md p-3 cursor-grab select-none hover:border-accent-blue/60 transition-colors"
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-mono text-fg-dim bg-[#21262d] px-1.5 py-0.5 rounded">
          {item.id}
        </span>
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded border ${priorityClass}`}
        >
          {(item.priority ?? "medium").toUpperCase()}
        </span>
      </div>
      <h3 className="text-sm font-medium text-fg leading-snug mb-2">
        {item.title}
      </h3>
      <div className="flex flex-wrap gap-1.5 items-center text-[11px]">
        {item.category && (
          <span className="text-fg-muted bg-[#21262d] px-1.5 py-0.5 rounded">
            {item.category}
          </span>
        )}
        {item.company && (
          <span className="text-accent-purple/90 bg-[#1f1530] border border-[#382858] px-1.5 py-0.5 rounded">
            {item.company}
          </span>
        )}
      </div>
      {(lessonHref || leetcodeHref || item.flashcard_topic) && (
        <div className="mt-2 flex items-center gap-3 text-[11px]">
          {lessonHref && (
            <Link
              href={lessonHref}
              className="text-accent-blue hover:underline"
              onPointerDown={(e) => e.stopPropagation()}
            >
              Lesson
            </Link>
          )}
          {leetcodeHref && (
            <a
              href={leetcodeHref}
              target="_blank"
              rel="noopener noreferrer"
              className="text-fg-muted hover:text-accent-blue hover:underline"
              onPointerDown={(e) => e.stopPropagation()}
            >
              LC{item.leetcode_num ? `#${item.leetcode_num}` : ""}
            </a>
          )}
          {item.flashcard_topic && onFlashcards && (
            <button
              className="text-accent-purple hover:underline"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); onFlashcards(item.flashcard_topic!); }}
            >
              ▤ Flashcards
            </button>
          )}
        </div>
      )}
    </motion.div>
  );
}
