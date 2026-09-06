/** One template variable derived from a loaded YAML/JSON file. */
export interface ParsedVariableEntry {
  name: string;
  value: string;
}

/**
 * Flatten a parsed YAML/JSON document into template-variable entries.
 *
 * Only **top-level** keys become variables. String values are kept verbatim;
 * numbers / booleans / null are stringified; nested objects and arrays become
 * pretty-printed JSON (matching how the editor stores the `device` / `nautobot`
 * / `commands` auto-variables, which `use-template-render` re-parses).
 *
 * Throws when the document is not a top-level mapping.
 */
export function flattenVariablesRecord(parsed: unknown): ParsedVariableEntry[] {
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(
      "File must contain a top-level mapping of variable names to values.",
    );
  }

  return Object.entries(parsed as Record<string, unknown>).map(([name, value]) => ({
    name: name.trim(),
    value: stringifyValue(value),
  }));
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === null || typeof value !== "object") {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}
