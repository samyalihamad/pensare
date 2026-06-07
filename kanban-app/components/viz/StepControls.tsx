"use client";

import { useEffect } from "react";

export default function StepControls({
  step,
  total,
  onPrev,
  onNext,
  onJump,
}: {
  step: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  onJump: (idx: number) => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        onNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        onPrev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onPrev, onNext]);

  return (
    <div className="flex items-center gap-3 py-2">
      <button
        type="button"
        onClick={onPrev}
        disabled={step <= 0}
        className="px-3 py-1 text-sm border border-border rounded bg-[#21262d] text-fg-muted hover:text-fg hover:border-accent-blue disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        ← Prev
      </button>
      <div className="flex gap-1.5">
        {Array.from({ length: total }, (_, i) => (
          <button
            key={i}
            type="button"
            aria-label={`Jump to step ${i + 1}`}
            onClick={() => onJump(i)}
            className={`w-2.5 h-2.5 rounded-full transition-colors ${
              i === step ? "bg-accent-blue" : "bg-[#30363d] hover:bg-[#484f58]"
            }`}
          />
        ))}
      </div>
      <button
        type="button"
        onClick={onNext}
        disabled={step >= total - 1}
        className="px-3 py-1 text-sm border border-border rounded bg-[#21262d] text-fg-muted hover:text-fg hover:border-accent-blue disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        Next →
      </button>
      <span className="ml-2 text-xs text-fg-dim">
        {step + 1} / {total}
      </span>
    </div>
  );
}
