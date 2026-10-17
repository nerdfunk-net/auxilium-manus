export type NameMatchMode = "exact" | "contains" | "regex";

export const NAME_MATCH_OPTIONS: ReadonlyArray<{
  value: NameMatchMode;
  label: string;
}> = [
  { value: "exact", label: "Exact name" },
  { value: "contains", label: "Contains (case-insensitive)" },
  { value: "regex", label: "Regular expression" },
];

export const DEFAULT_INDEX_REGEX = ":(\\d+)";
export const DEFAULT_INDEX_OFFSET = -1;
export const DEFAULT_INDEX_DEFAULT = 0;
export const DEFAULT_ATTRIBUTE_BAG = "virtual_chassis";
export const DEFAULT_INDEX_KEY = "stack_index";

export function nameMatchFromConfig(config: Record<string, unknown>): NameMatchMode {
  const raw = config.name_match;
  return raw === "contains" || raw === "regex" ? raw : "exact";
}

export function stringFromConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : fallback;
}

export function intFromConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const raw = config[key];
  return typeof raw === "number" && Number.isInteger(raw) ? raw : fallback;
}
