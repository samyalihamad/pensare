import { NextRequest, NextResponse } from "next/server";
import { loadContext } from "@/lib/context";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const project = req.nextUrl.searchParams.get("project") ?? "interview-prep";
  const relPath = req.nextUrl.searchParams.get("path");
  if (!relPath) {
    return NextResponse.json({ error: "Missing path" }, { status: 400 });
  }
  try {
    const data = await loadContext(project, relPath);
    return NextResponse.json(data);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 404 });
  }
}
