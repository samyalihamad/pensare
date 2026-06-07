import { NextRequest, NextResponse } from "next/server";
import { loadBoard } from "@/lib/board";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const project = req.nextUrl.searchParams.get("project") ?? "interview-prep";
  try {
    const data = await loadBoard(project);
    return NextResponse.json({ project, ...data });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
