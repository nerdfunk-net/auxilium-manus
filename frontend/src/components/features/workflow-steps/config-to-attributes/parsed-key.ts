import type { SourceFormat } from "./types";

/** Formats whose upstream step writes `parsed[<node id>][<output_key>]` (Get & Parse Config,
 * Extract Facts). The others write the flat `parsed[<output_key>]`. */
const NESTED_FORMATS: ReadonlySet<SourceFormat> = new Set<SourceFormat>(["genie", "batfish"]);

export function isNestedFormat(format: SourceFormat): boolean {
  return NESTED_FORMATS.has(format);
}

/** Sub-keys the readers look at inside an entry; the `parsed_key` ends before them. */
const ENTRY_SUBKEY = /\.(?:running|startup|parsed)(?:[.[]|$)/;

/**
 * The attribute path picker returns a full dotted path such as
 * "parsed.pyats_config.running" (flat formats) or
 * "parsed.get-pyats-1.pyats_config.running" (nested formats). `parsed_key` is the part between
 * "parsed." and the entry's own sub-key: one segment for a flat format, `<node id>.<output_key>`
 * for a nested one. Any other shape is returned unchanged.
 */
export function parsedKeyFromAttributePath(path: string, format: SourceFormat): string {
  const rest = /^parsed\.(.+)$/.exec(path)?.[1];
  if (rest === undefined) return path;
  if (!isNestedFormat(format)) {
    return /^([^.[]+)/.exec(rest)?.[1] ?? path;
  }
  const cut = ENTRY_SUBKEY.exec(`.${rest}`);
  const key = cut ? `.${rest}`.slice(1, cut.index) : rest;
  return key || path;
}
