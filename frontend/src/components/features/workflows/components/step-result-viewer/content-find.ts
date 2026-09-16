/**
 * Case-insensitive, non-overlapping matches for ContentViewer find.
 * Offsets are taken from the original string (including the matched
 * length) so highlighting stays correct when case folding changes width.
 */
export interface ContentMatch {
  start: number;
  length: number;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function findMatches(content: string, query: string): ContentMatch[] {
  if (!query) {
    return [];
  }

  const regex = new RegExp(escapeRegExp(query), "gi");
  const matches: ContentMatch[] = [];
  let result: RegExpExecArray | null;

  while ((result = regex.exec(content)) !== null) {
    matches.push({ start: result.index, length: result[0].length });
    if (result[0].length === 0) {
      regex.lastIndex += 1;
    }
  }

  return matches;
}

export function wrapMatchIndex(activeMatch: number, matchCount: number): number {
  if (matchCount === 0) {
    return 0;
  }
  return ((activeMatch % matchCount) + matchCount) % matchCount;
}
