import { diffLines } from "diff";

export type DiffRowKind = "added" | "removed" | "context" | "gap";

export interface DiffRow {
  kind: DiffRowKind;
  /** The line text (empty for a gap). */
  text: string;
  /** For a gap: how many unchanged lines are hidden. */
  hidden?: number;
}

export interface LineDiff {
  rows: DiffRow[];
  added: number;
  removed: number;
}

const CONTEXT_LINES = 3;

function splitLines(value: string): string[] {
  const lines = value.split("\n");
  // A trailing newline yields one empty tail element that is not a real line.
  if (lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }
  return lines;
}

/**
 * Line diff of two texts, with long unchanged runs collapsed into a single gap row so a large
 * template with a small change stays readable.
 */
export function buildLineDiff(before: string, after: string): LineDiff {
  const all: DiffRow[] = [];
  let added = 0;
  let removed = 0;

  for (const part of diffLines(before, after)) {
    const kind: DiffRowKind = part.added
      ? "added"
      : part.removed
        ? "removed"
        : "context";
    for (const text of splitLines(part.value)) {
      all.push({ kind, text });
      if (kind === "added") added += 1;
      if (kind === "removed") removed += 1;
    }
  }

  const keep = all.map((row) => row.kind !== "context");
  all.forEach((row, index) => {
    if (row.kind === "context") return;
    for (let offset = -CONTEXT_LINES; offset <= CONTEXT_LINES; offset += 1) {
      const neighbour = index + offset;
      if (neighbour >= 0 && neighbour < all.length) keep[neighbour] = true;
    }
  });

  const rows: DiffRow[] = [];
  let hidden = 0;
  all.forEach((row, index) => {
    if (keep[index]) {
      if (hidden > 0) {
        rows.push({ kind: "gap", text: "", hidden });
        hidden = 0;
      }
      rows.push(row);
    } else {
      hidden += 1;
    }
  });
  if (hidden > 0) rows.push({ kind: "gap", text: "", hidden });

  return { rows, added, removed };
}
