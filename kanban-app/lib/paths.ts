import os from "node:os";
import path from "node:path";

export const CONTEXTS_ROOT = path.join(os.homedir(), ".claude", "contexts");

export function projectDir(project: string): string {
  return path.join(CONTEXTS_ROOT, project);
}

export function kanbanDir(project: string): string {
  return path.join(projectDir(project), "kanban");
}

export function itemsDir(project: string): string {
  return path.join(kanbanDir(project), "items");
}

export function itemPath(project: string, id: string): string {
  return path.join(itemsDir(project), `${id}.md`);
}

export function configPath(project: string): string {
  return path.join(kanbanDir(project), "config.json");
}

export function indexPath(project: string): string {
  return path.join(kanbanDir(project), "INDEX.md");
}

/**
 * Safely resolve a context-relative path. Throws if the path escapes the
 * project's context directory.
 */
export function resolveContextPath(project: string, relative: string): string {
  const root = projectDir(project);
  const resolved = path.resolve(root, relative);
  const rel = path.relative(root, resolved);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`Path escapes project context: ${relative}`);
  }
  return resolved;
}

/**
 * Safely resolve a kanban-item id to a markdown file path. Throws on path
 * traversal.
 */
export function resolveItemPath(project: string, id: string): string {
  if (!/^[A-Za-z0-9_-]+$/.test(id)) {
    throw new Error(`Invalid item id: ${id}`);
  }
  return itemPath(project, id);
}
