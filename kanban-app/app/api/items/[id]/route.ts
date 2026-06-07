import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import { regenerateIndex, updateItem } from "@/lib/board";
import { resolveItemPath } from "@/lib/paths";

export const dynamic = "force-dynamic";

type Params = { params: { id: string } };

export async function PATCH(req: NextRequest, { params }: Params) {
  const project = req.nextUrl.searchParams.get("project") ?? "interview-prep";
  const id = params.id;

  let filePath: string;
  try {
    filePath = resolveItemPath(project, id);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 400 });
  }

  try {
    await fs.access(filePath);
  } catch {
    return NextResponse.json({ error: `Item ${id} not found` }, { status: 404 });
  }

  let updates: { status?: string; priority?: string; title?: string; note?: string };
  try {
    updates = (await req.json()) as typeof updates;
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  try {
    await updateItem(project, id, updates);
    await regenerateIndex(project);
    return NextResponse.json({ ok: true });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
