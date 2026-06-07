"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Flashcard = { front: string; back: string };

export default function FlashcardModal({
  project,
  topic,
  onClose,
}: {
  project: string;
  topic: string;
  onClose: () => void;
}) {
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/flashcards?project=${encodeURIComponent(project)}&topic=${encodeURIComponent(topic)}`)
      .then((r) => r.json())
      .then((data: { error?: string; cards?: Flashcard[] }) => {
        if (data.error) throw new Error(data.error);
        setCards(data.cards ?? []);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [project, topic]);

  const prev = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);
  const next = useCallback(
    () => setIndex((i) => Math.min((cards.length || 1) - 1, i + 1)),
    [cards.length],
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        next();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose, prev, next]);

  const card = cards[index];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-[#161b22] border border-border rounded-xl w-full max-w-2xl mx-4 flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-muted">
          <span className="text-xs text-accent-purple font-mono uppercase tracking-wide">
            {topic}
          </span>
          <div className="flex items-center gap-3">
            {cards.length > 0 && (
              <span className="text-xs text-fg-muted">
                {index + 1} / {cards.length}
              </span>
            )}
            <button
              onClick={onClose}
              className="text-fg-muted hover:text-fg text-xl leading-none"
            >
              ×
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && <p className="text-fg-muted text-sm">Loading…</p>}
          {error && <p className="text-accent-red text-sm">{error}</p>}
          {card && (
            <>
              <h2 className="text-base font-semibold text-fg mb-4">{card.front}</h2>
              <div className="markdown text-sm">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{card.back}</ReactMarkdown>
              </div>
            </>
          )}
        </div>

        {cards.length > 0 && (
          <div className="flex justify-center gap-1.5 py-2">
            {cards.map((_, i) => (
              <button
                key={i}
                onClick={() => setIndex(i)}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i === index
                    ? "bg-accent-purple"
                    : "bg-fg-dim hover:bg-fg-muted"
                }`}
              />
            ))}
          </div>
        )}

        <div className="flex items-center justify-between px-5 py-3 border-t border-border-muted">
          <button
            onClick={prev}
            disabled={index === 0}
            className="px-3 py-1.5 text-sm text-fg-muted hover:text-fg disabled:opacity-30 disabled:cursor-not-allowed"
          >
            ← Prev
          </button>
          <span className="text-[11px] text-fg-dim">← → Space to navigate · Esc to close</span>
          <button
            onClick={next}
            disabled={index >= cards.length - 1}
            className="px-3 py-1.5 text-sm text-fg-muted hover:text-fg disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}
