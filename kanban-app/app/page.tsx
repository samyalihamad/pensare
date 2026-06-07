import { Suspense } from "react";
import KanbanBoard from "@/components/board/KanbanBoard";

export const dynamic = "force-dynamic";

export default function Page({
  searchParams,
}: {
  searchParams: { project?: string };
}) {
  const project = searchParams.project ?? "interview-prep";
  return (
    <Suspense fallback={<div className="p-6 text-fg-muted">Loading board…</div>}>
      <KanbanBoard project={project} />
    </Suspense>
  );
}
