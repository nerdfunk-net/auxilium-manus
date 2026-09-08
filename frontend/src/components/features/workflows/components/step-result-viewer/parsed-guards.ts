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

/**
 * compare-pyats-snapshot stores `{nodeId}.comparison_diff` as a
 * `{ feature: ParsedComparisonDiffEntry }` map (one entry per differing Genie
 * feature) rather than the single flat entry compare-data writes. Both shapes
 * must render in the detail view.
 */
function isComparisonDiffFeatureMap(
  value: unknown,
): value is Record<string, ParsedComparisonDiffEntry> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const entries = Object.values(value as Record<string, unknown>);
  return entries.length > 0 && entries.every(isComparisonDiffEntry);
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
  const result: Array<{ key: string; entry: ParsedComparisonDiffEntry }> = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (isComparisonDiffEntry(value)) {
      result.push({ key, entry: value });
    } else if (isComparisonDiffFeatureMap(value)) {
      for (const [feature, entry] of Object.entries(value)) {
        result.push({ key: `${key} · ${feature}`, entry });
      }
    }
  }
  return result;
}

export function isGenieParsedConfigEntry(value: unknown): value is GenieParsedConfigEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  if (
    isParsedTemplateEntry(value) ||
    isComparisonResultEntry(value) ||
    isComparisonDiffEntry(value) ||
    isComparisonDiffFeatureMap(value)
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
    isComparisonDiffFeatureMap(value) ||
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
