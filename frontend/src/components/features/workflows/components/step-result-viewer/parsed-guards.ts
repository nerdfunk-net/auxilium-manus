import type {
  ParsedCommandEntry,
  ParsedCommandOutputEntry,
  ParsedComparisonDiffEntry,
  ParsedComparisonResultEntry,
  ParsedConfigEntry,
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

export function isParsedConfigEntry(value: unknown): value is ParsedConfigEntry {
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

export function getParsedConfigEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedConfigEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isParsedConfigEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedConfigEntry }));
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
    isParsedConfigEntry(value) ||
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

/**
 * A bare `{parsed, error}` entry directly under `device.parsed[key]` — the
 * shape batfish-extract-facts, batfish-validate-facts, and the `devices`
 * outcome of batfish-node-properties/batfish-interface-properties all write
 * (`device.parsed[f"{node_id}.{output_key}"] = {"parsed": ..., "error": ...}`).
 * Distinct from `ParsedCommandOutputEntry`, which is a *map* of these
 * entries keyed by command name — this is the entry itself, one level up.
 * Checked last, after every more specific guard, since those shapes could
 * otherwise also satisfy `"parsed" in value && "error" in value` structurally
 * (e.g. a single-key command-output map is not this, but is excluded
 * explicitly below since object identity alone can't tell them apart).
 */
export function isFactsEntry(value: unknown): value is ParsedCommandEntry {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  if (
    isParsedTemplateEntry(value) ||
    isComparisonResultEntry(value) ||
    isComparisonDiffEntry(value) ||
    isComparisonDiffFeatureMap(value) ||
    isParsedConfigEntry(value) ||
    isSnapshotEntry(value) ||
    isParsedCommandOutputEntry(value)
  ) {
    return false;
  }
  return isParsedCommandEntry(value);
}

export function getFactsEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedCommandEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isFactsEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedCommandEntry }));
}
