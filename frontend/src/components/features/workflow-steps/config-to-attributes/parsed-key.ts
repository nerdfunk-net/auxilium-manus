import type { SourceFormat } from "./types";

/** Formats whose upstream step writes `parsed[<node id>][<output_key>]` (Get & Parse Config,
 * Extract Facts). The others write the flat `parsed[<output_key>]`. */
const NESTED_FORMATS: ReadonlySet<SourceFormat> = new Set<SourceFormat>(["genie", "batfish"]);

export function isNestedFormat(format: SourceFormat): boolean {
  return NESTED_FORMATS.has(format);
}

/** One path segment: up to the next dot or bracket. */
const SEGMENT = "[^.[]+";
const FIRST_SEGMENT = new RegExp(`^(${SEGMENT})`);
const FIRST_TWO_SEGMENTS = new RegExp(`^(${SEGMENT}\\.${SEGMENT})`);

/**
 * The attribute path picker returns a full dotted path such as
 * "parsed.pyats_config.running" (flat formats) or
 * "parsed.get-pyats-1.pyats_config.running" (nested formats). `parsed_key` is the leading part
 * after "parsed.": one segment for a flat format, `<node id>.<output_key>` (two segments) for a
 * nested one. Neither a node id nor an output key contains a dot, so the key is counted by
 * segments, never cut at a sub-key name: an output key may itself be called "parsed" or
 * "running". Any other shape is returned unchanged.
 */
export function parsedKeyFromAttributePath(path: string, format: SourceFormat): string {
  const rest = /^parsed\.(.+)$/.exec(path)?.[1];
  if (rest === undefined) return path;
  const pattern = isNestedFormat(format) ? FIRST_TWO_SEGMENTS : FIRST_SEGMENT;
  return pattern.exec(rest)?.[1] ?? rest;
}
