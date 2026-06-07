import { Suspense } from "react";
import LessonViewer from "@/components/lesson/LessonViewer";

export const dynamic = "force-dynamic";

export default function LessonPage({
  searchParams,
}: {
  searchParams: { project?: string; path?: string };
}) {
  const project = searchParams.project ?? "interview-prep";
  const relPath = searchParams.path ?? "";
  return (
    <Suspense fallback={<div className="p-6 text-fg-muted">Loading lesson…</div>}>
      <LessonViewer project={project} path={relPath} />
    </Suspense>
  );
}
