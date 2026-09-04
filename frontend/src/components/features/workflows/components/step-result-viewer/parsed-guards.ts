import type {
  GenieParsedConfigEntry,
  ParsedCommandEntry,
  ParsedCommandOutputEntry,
  ParsedComparisonDiffEntry,
  ParsedComparisonResultEntry,
  ParsedTemplateEntry,
  SnapshotEntry,
} from "./types";

export function isParsedTemplateEntry(value: unknown): value is ParsedTemplateEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as ParsedTemplateEntry;
  return (
    typeof entry.artifact_ref === "object" &&
    entry.artifact_ref !== null &&
    typeof entry.artifact_ref.artifact_id === "string" &&
    typeof entry.output_key === "string"
  );
}

export function getParsedTemplateEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedTemplateEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isParsedTemplateEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedTemplateEntry }));
}

export function isComparisonResultEntry(value: unknown): value is ParsedComparisonResultEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as ParsedComparisonResultEntry).kind === "comparison_result"
  );
}

export function isComparisonDiffEntry(value: unknown): value is ParsedComparisonDiffEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as ParsedComparisonDiffEntry;
  return (
    entry.kind === "comparison_diff" &&
    typeof entry.artifact_ref === "object" &&
    entry.artifact_ref !== null &&
    typeof entry.artifact_ref.artifact_id === "string"
  );
}

export function getComparisonResultEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedComparisonResultEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isComparisonResultEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedComparisonResultEntry }));
}

export function getComparisonDiffEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedComparisonDiffEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isComparisonDiffEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedComparisonDiffEntry }));
}

export function isGenieParsedConfigEntry(value: unknown): value is GenieParsedConfigEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  if (
    isParsedTemplateEntry(value) ||
    isComparisonResultEntry(value) ||
    isComparisonDiffEntry(value)
  ) {
    return false;
  }
  return "running" in value || "startup" in value;
}

export function getGenieParsedConfigEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: GenieParsedConfigEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isGenieParsedConfigEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as GenieParsedConfigEntry }));
}

export function isSnapshotEntry(value: unknown): value is SnapshotEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as SnapshotEntry;
  return (
    entry.kind === "pyats_snapshot" &&
    typeof entry.artifact_ref === "object" &&
    entry.artifact_ref !== null &&
    typeof entry.artifact_ref.artifact_id === "string" &&
    typeof entry.features === "object" &&
    entry.features !== null
  );
}

export function getSnapshotEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: SnapshotEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isSnapshotEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as SnapshotEntry }));
}

function isParsedCommandEntry(value: unknown): value is ParsedCommandEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    "parsed" in value &&
    "error" in value
  );
}

/** run-command's normalized `{"<command>": {parsed, error}}` output — see
 * `ParsedCommandOutputEntry` in ./types. */
export function isParsedCommandOutputEntry(
  value: unknown,
): value is ParsedCommandOutputEntry {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  if (
    isParsedTemplateEntry(value) ||
    isComparisonResultEntry(value) ||
    isComparisonDiffEntry(value) ||
    isGenieParsedConfigEntry(value) ||
    isSnapshotEntry(value)
  ) {
    return false;
  }
  const commandEntries = Object.values(value as Record<string, unknown>);
  return commandEntries.length > 0 && commandEntries.every(isParsedCommandEntry);
}

export function getParsedCommandOutputEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedCommandOutputEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isParsedCommandOutputEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedCommandOutputEntry }));
}
