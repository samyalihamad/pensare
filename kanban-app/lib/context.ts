import { promises as fs } from "node:fs";
import path from "node:path";
import { resolveContextPath } from "./paths";

export type ContextResponse = {
  title: string;
  markdown: string;
  vizData: unknown | null;
};

/**
 * Load a markdown file and any sidecar `<stem>.viz.json` viz data.
 * The Python server inlined viz data as fenced code blocks; this version
 * keeps the markdown clean and reads viz from a sidecar JSON.
 */
export async function loadContext(
  project: string,
  relPath: string,
): Promise<ContextResponse> {
  const target = resolveContextPath(project, relPath);
  const markdown = await fs.readFile(target, "utf8");

  const dir = path.dirname(target);
  const stem = path.basename(target, path.extname(target));
  const vizPath = path.join(dir, `${stem}.viz.json`);

  let vizData: unknown | null = null;
  try {
    const raw = await fs.readFile(vizPath, "utf8");
    vizData = JSON.parse(raw);
  } catch {
    vizData = null;
  }

  return { title: stem, markdown, vizData };
}
