import type { WorkflowSummary } from "../types/workflow-persistence";

export const FOLDER_ROOT = "/";

export function normalizeFolder(folder: string | null | undefined): string {
  if (!folder || folder === "") return FOLDER_ROOT;
  return folder;
}

export function getFolderLabel(folder: string | null | undefined): string {
  const normalized = normalizeFolder(folder);
  if (normalized === FOLDER_ROOT) return "Root";
  return normalized.replace(/^\//, "");
}

export function buildFolderCounts(workflows: WorkflowSummary[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const wf of workflows) {
    const f = normalizeFolder(wf.folder);
    map.set(f, (map.get(f) ?? 0) + 1);
  }
  return map;
}

export function getSortedFolders(folderCounts: Map<string, number>): string[] {
  return Array.from(folderCounts.keys()).sort((a, b) => {
    if (a === FOLDER_ROOT) return -1;
    if (b === FOLDER_ROOT) return 1;
    return a.localeCompare(b);
  });
}
