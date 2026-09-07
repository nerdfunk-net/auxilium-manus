/** One template variable derived from a loaded YAML/JSON file. */
export interface ParsedVariableEntry {
  name: string;
  value: string;
}

/**
 * First path segments the `read-from-file` step refuses as a destination.
 * Mirrors `backend/workflow_steps/common/attribute_merge.py::validate_merge_destination`
 * (device scalar fields + the engine-owned `parsed` / `run_input` bags), so a
 * path accepted here is also accepted by the step.
 */
const RESERVED_DESTINATION_ROOTS = new Set([
  "id",
  "name",
  "hostname",
  "platform",
  "network_driver",
  "primary_ip4",
  "source",
  "source_id",
  "parsed",
  "run_input",
]);

/**
 * Validate a `read-from-file`-style destination path and return its trimmed
 * form. Throws with a user-facing message on an empty path, a `device.`-prefixed
 * path, an empty segment, or a reserved first segment.
 */
export function validateDestinationPath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) {
    throw new Error("Destination path is required.");
  }
  if (trimmed.startsWith("device.")) {
    throw new Error("Destination path cannot target device.* fields.");
  }
  const segments = trimmed.split(".");
  if (segments.some((segment) => segment.trim() === "")) {
    throw new Error("Destination path segments cannot be empty.");
  }
  if (RESERVED_DESTINATION_ROOTS.has(segments[0])) {
    throw new Error(
      `"${segments[0]}" is a reserved namespace and cannot be a destination path.`,
    );
  }
  return trimmed;
}

/**
 * Flatten a parsed YAML/JSON document into template-variable entries.
 *
 * Only **top-level** keys become variables. String values are kept verbatim;
 * numbers / booleans / null are stringified; nested objects and arrays become
 * pretty-printed JSON (matching how the editor stores the `device` / `nautobot`
 * / `commands` auto-variables, which `use-template-render` re-parses).
 *
 * When `destinationPath` is given, every key is prefixed with it
 * (`data` → `data.snmp1`) so the resulting variables land under the same
 * namespace the `read-from-file` step merges into at runtime — a template
 * previewed in the editor then renders identically in the workflow. The path is
 * validated with {@link validateDestinationPath}.
 *
 * Throws when the document is not a top-level mapping, or the path is invalid.
 */
export function flattenVariablesRecord(
  parsed: unknown,
  destinationPath?: string,
): ParsedVariableEntry[] {
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(
      "File must contain a top-level mapping of variable names to values.",
    );
  }

  const prefix =
    destinationPath === undefined
      ? ""
      : `${validateDestinationPath(destinationPath)}.`;

  return Object.entries(parsed as Record<string, unknown>).map(([name, value]) => ({
    name: `${prefix}${name.trim()}`,
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
