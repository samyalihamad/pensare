import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

export const dynamic = "force-dynamic";

type Flashcard = { front: string; back: string };

function parseCards(content: string): Flashcard[] {
  const lines = content.split(/\r?\n/);
  let bodyStart = 0;
  if (lines[0]?.trim() === "---") {
    for (let i = 1; i < lines.length; i++) {
      if (lines[i].trim() === "---") {
        bodyStart = i + 1;
        break;
      }
    }
  }
  const body = lines.slice(bodyStart).join("\n");
  const sections = body.split(/\n---\n/);
  const cards: Flashcard[] = [];
  for (const section of sections) {
    const trimmed = section.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^##\s+(.+)/m);
    if (!match) continue;
    const front = match[1].trim();
    const back = trimmed.replace(/^##\s+[^\n]+\n?/, "").trim();
    if (front && back) cards.push({ front, back });
  }
  return cards;
}

export async function GET(req: NextRequest) {
  const project = req.nextUrl.searchParams.get("project");
  const topic = req.nextUrl.searchParams.get("topic");

  if (!project || !topic) {
    return NextResponse.json({ error: "project and topic required" }, { status: 400 });
  }
  if (!/^[A-Za-z0-9_-]+$/.test(project) || !/^[A-Za-z0-9_-]+$/.test(topic)) {
    return NextResponse.json({ error: "invalid project or topic" }, { status: 400 });
  }

  const kbPath = path.join(os.homedir(), ".claude", "contexts", project, "kb", `${topic}.md`);
  try {
    const content = await fs.readFile(kbPath, "utf8");
    return NextResponse.json({ topic, cards: parseCards(content) });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 404 });
  }
}
