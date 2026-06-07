import { promises as fs } from "node:fs";
import path from "node:path";
import {
  configPath,
  itemsDir,
  indexPath,
  resolveItemPath,
} from "./paths";

export type ItemMeta = {
  [key: string]: string | undefined;
  _body?: string;
  _ref_label?: string;
  _ref_path?: string;
};

export type BoardConfig = {
  columns: string[];
  categories: string[];
  id_prefix: string;
  next_id: number;
};

const DEFAULT_CONFIG: BoardConfig = {
  columns: ["Backlog", "In Progress", "Blocked", "Done"],
  categories: [],
  id_prefix: "KB",
  next_id: 1,
};

const PRIORITY_ORDER: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/**
 * Parse YAML frontmatter at the top of a markdown document. Mirrors the
 * lightweight parser used by the Python server — supports simple
 * `key: value` lines, no nested structures.
 */
export function parseFrontmatter(content: string): { meta: ItemMeta; body: string } {
  const lines = content.split(/\r?\n/);
  if (lines.length === 0 || lines[0].trim() !== "---") {
    return { meta: {} as ItemMeta, body: content };
  }

  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === "---") {
      end = i;
      break;
    }
  }

  if (end === -1) {
    return { meta: {} as ItemMeta, body: content };
  }

  const meta: ItemMeta = {} as ItemMeta;
  for (let i = 1; i < end; i++) {
    const line = lines[i];
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    const key = line.slice(0, colon).trim();
    let val = line.slice(colon + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (key) {
      meta[key] = val;
    }
  }

  const body = lines.slice(end + 1).join("\n").trim();
  return { meta, body };
}

/**
 * Find the first markdown link in a `## Reference` section.
 * Returns [label, relativePath] or ["", ""] if none found.
 */
export function parseReference(body: string): [string, string] {
  const lines = body.split(/\r?\n/);
  let inRef = false;
  const linkRe = /\[([^\]]+)\]\(([^)]+)\)/;
  for (const line of lines) {
    if (line.trim() === "## Reference") {
      inRef = true;
      continue;
    }
    if (inRef) {
      const m = line.match(linkRe);
      if (m) return [m[1], m[2]];
      if (line.startsWith("## ")) break;
    }
  }
  return ["", ""];
}

/**
 * Map a status slug back to its display column name. Tolerates either
 * lower-case slugs ("in-progress") or column-name case ("In Progress").
 */
export function slugToColumn(slug: string, columns: string[]): string {
  const norm = (s: string) => s.toLowerCase().replace(/\s+/g, "-");
  const target = norm(slug);
  for (const col of columns) {
    if (norm(col) === target || col.toLowerCase() === slug.toLowerCase()) {
      return col;
    }
  }
  return columns[0] ?? slug;
}

export async function loadConfig(project: string): Promise<BoardConfig> {
  try {
    const raw = await fs.readFile(configPath(project), "utf8");
    const cfg = JSON.parse(raw) as Partial<BoardConfig>;
    return { ...DEFAULT_CONFIG, ...cfg } as BoardConfig;
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export async function loadBoard(project: string): Promise<{
  config: BoardConfig;
  columns: string[];
  board: Record<string, ItemMeta[]>;
  total: number;
}> {
  const config = await loadConfig(project);
  const columns = config.columns;

  let entries: string[] = [];
  try {
    entries = (await fs.readdir(itemsDir(project)))
      .filter((f) => f.endsWith(".md"))
      .sort();
  } catch {
    entries = [];
  }

  const items: ItemMeta[] = [];
  for (const name of entries) {
    const full = path.join(itemsDir(project), name);
    let content: string;
    try {
      content = await fs.readFile(full, "utf8");
    } catch {
      continue;
    }
    const { meta, body } = parseFrontmatter(content);
    if (Object.keys(meta).length === 0) continue;
    const [refLabel, refPath] = parseReference(body);
    meta._body = body;
    meta._ref_label = refLabel;
    meta._ref_path = refPath;
    if (!("leetcode_num" in meta)) meta.leetcode_num = "";
    if (!("leetcode_slug" in meta)) meta.leetcode_slug = "";
    items.push(meta);
  }

  const board: Record<string, ItemMeta[]> = {};
  for (const col of columns) board[col] = [];

  for (const item of items) {
    const col = slugToColumn(item.status ?? "", columns);
    if (!board[col]) board[col] = [];
    board[col].push(item);
  }

  for (const col of Object.keys(board)) {
    board[col].sort((a, b) => {
      const pa = PRIORITY_ORDER[a.priority ?? "medium"] ?? 1;
      const pb = PRIORITY_ORDER[b.priority ?? "medium"] ?? 1;
      return pa - pb;
    });
  }

  return { config, columns, board, total: items.length };
}

/**
 * Update frontmatter fields and optionally append a note to the `## Notes`
 * section. Mirrors the Python `update_item` behavior — bumps `updated:` to
 * today's ISO date and preserves all other frontmatter lines verbatim.
 */
export async function updateItem(
  project: string,
  id: string,
  updates: { status?: string; priority?: string; title?: string; note?: string },
): Promise<void> {
  const filePath = resolveItemPath(project, id);
  const content = await fs.readFile(filePath, "utf8");
  const lines = content.split(/\r?\n/);

  if (lines.length === 0 || lines[0].trim() !== "---") {
    throw new Error("Missing frontmatter");
  }

  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) throw new Error("Unclosed frontmatter");

  const today = new Date().toISOString().slice(0, 10);
  const fmUpdates: Record<string, string> = {};
  for (const [k, v] of Object.entries(updates)) {
    if (k === "note" || v === undefined) continue;
    fmUpdates[k] = String(v);
  }
  fmUpdates.updated = today;

  const newFm: string[] = [lines[0]];
  for (let i = 1; i < end; i++) {
    const line = lines[i];
    const colon = line.indexOf(":");
    if (colon !== -1) {
      const key = line.slice(0, colon).trim();
      if (key in fmUpdates) {
        newFm.push(`${key}: ${fmUpdates[key]}`);
        delete fmUpdates[key];
        continue;
      }
    }
    newFm.push(line);
  }
  // Insert keys that were not already present.
  for (const [k, v] of Object.entries(fmUpdates)) {
    newFm.push(`${k}: ${v}`);
  }
  newFm.push(lines[end]);

  const bodyLines = lines.slice(end + 1);

  if (typeof updates.note === "string" && updates.note.length > 0) {
    const noteLine = `- ${today}: ${updates.note}`;
    let noteIdx = -1;
    for (let i = 0; i < bodyLines.length; i++) {
      if (bodyLines[i].trim() === "## Notes") {
        noteIdx = i;
        break;
      }
    }
    if (noteIdx === -1) {
      bodyLines.push("", "## Notes", "", noteLine);
    } else {
      bodyLines.splice(noteIdx + 1, 0, noteLine);
    }
  }

  const out = newFm.concat(bodyLines).join("\n").replace(/\n*$/, "\n");
  await fs.writeFile(filePath, out, "utf8");
}

/**
 * Rebuild INDEX.md from all item files. Mirrors the Python implementation.
 */
export async function regenerateIndex(project: string): Promise<void> {
  const config = await loadConfig(project);
  const columns = config.columns;

  let entries: string[] = [];
  try {
    entries = (await fs.readdir(itemsDir(project)))
      .filter((f) => f.endsWith(".md"))
      .sort();
  } catch {
    entries = [];
  }

  const items: ItemMeta[] = [];
  for (const name of entries) {
    const full = path.join(itemsDir(project), name);
    let content: string;
    try {
      content = await fs.readFile(full, "utf8");
    } catch {
      continue;
    }
    const { meta } = parseFrontmatter(content);
    if (Object.keys(meta).length > 0) items.push(meta);
  }

  const counts: Record<string, number> = {};
  for (const col of columns) counts[col] = 0;
  const active: ItemMeta[] = [];
  const done: ItemMeta[] = [];

  const doneCol = columns[columns.length - 1];

  for (const item of items) {
    const col = slugToColumn(item.status ?? "", columns);
    counts[col] = (counts[col] ?? 0) + 1;
    if (col === doneCol) done.push(item);
    else active.push(item);
  }

  active.sort((a, b) => {
    const pa = PRIORITY_ORDER[a.priority ?? "medium"] ?? 1;
    const pb = PRIORITY_ORDER[b.priority ?? "medium"] ?? 1;
    return pa - pb;
  });
  done.sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""));

  const today = new Date().toISOString().slice(0, 10);
  const projectName = project;

  const lines: string[] = [
    `# Kanban Board — ${projectName}`,
    "",
    `_Last updated: ${today}_`,
    "",
    "## Column Summary",
    "",
    "| Column | Count |",
    "|--------|-------|",
  ];
  for (const col of columns) {
    lines.push(`| ${col} | ${counts[col] ?? 0} |`);
  }

  lines.push("", "## Active Items", "");
  if (active.length > 0) {
    lines.push(
      "| ID | Title | Status | Category | Priority |",
      "|----|-------|--------|----------|----------|",
    );
    for (const item of active) {
      lines.push(
        `| ${item.id ?? "—"} | ${item.title ?? "—"} | ${item.status ?? "—"} | ${item.category ?? ""} | ${item.priority ?? "—"} |`,
      );
    }
  } else {
    lines.push("_No active items._");
  }

  lines.push("", "## Recently Completed (last 5)", "");
  if (done.length > 0) {
    lines.push(
      "| ID | Title | Category | Updated |",
      "|----|-------|----------|---------|",
    );
    for (const item of done.slice(0, 5)) {
      lines.push(
        `| ${item.id ?? "—"} | ${item.title ?? "—"} | ${item.category ?? ""} | ${item.updated ?? "—"} |`,
      );
    }
  } else {
    lines.push("_No completed items yet._");
  }

  await fs.writeFile(indexPath(project), lines.join("\n") + "\n", "utf8");
}
