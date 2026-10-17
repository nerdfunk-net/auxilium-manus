import type {
  ParsedCommandEntry,
  ParsedCommandOutputEntry,
  ParsedComparisonDiffEntry,
  ParsedComparisonResultEntry,
  ParsedConfigEntry,
  ParsedContentMatchEntry,
  ParsedMembershipEntry,
  ParsedTemplateEntry,
  SnapshotEntry,
} from "./types";

/**
 * Every step that stashes its own per-run result under its own canvas node id
 * (route-on-content, list-contains, compare-data, compare-pyats-snapshot,
 * reachable, login-successful, merge-content, configure-replace-config,
 * filter-output, update-content, the batfish property/facts steps, ...)
 * nests it as `parsed[node_id][key] = <entry>` (see
 * `backend/services/workflow_context/node_result.py`) instead of a flat
 * `parsed[output_key] = <entry>` a user chose themselves. A top-level
 * `device.parsed` value that isn't itself one of the recognized entry shapes
 * below is therefore treated as a per-node result bag and searched one level
 * deeper, so every `get*Entries` helper below sees both kinds of entry
 * uniformly.
 */
function isKnownParsedEntry(value: unknown): boolean {
  return (
    isParsedTemplateEntry(value) ||
    isComparisonResultEntry(value) ||
    isComparisonDiffEntry(value) ||
    isComparisonDiffFeatureMap(value) ||
    isParsedConfigEntry(value) ||
    isSnapshotEntry(value) ||
    isParsedCommandOutputEntry(value) ||
    isFactsEntry(value) ||
    isContentMatchEntry(value) ||
    isMembershipEntry(value)
  );
}

function flattenParsedEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; value: unknown }> {
  const out: Array<{ key: string; value: unknown }> = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (
      isKnownParsedEntry(value) ||
      typeof value !== "object" ||
      value === null ||
      Array.isArray(value)
    ) {
      out.push({ key, value });
      continue;
    }
    for (const [innerKey, innerValue] of Object.entries(value as Record<string, unknown>)) {
      out.push({ key: `${key}.${innerKey}`, value: innerValue });
    }
  }
  return out;
}

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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isParsedTemplateEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedTemplateEntry }));
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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isComparisonResultEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedComparisonResultEntry }));
}

export function getComparisonDiffEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedComparisonDiffEntry }> {
  const result: Array<{ key: string; entry: ParsedComparisonDiffEntry }> = [];
  for (const { key, value } of flattenParsedEntries(parsed)) {
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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isParsedConfigEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedConfigEntry }));
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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isSnapshotEntry(value))
    .map(({ key, value }) => ({ key, entry: value as SnapshotEntry }));
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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isParsedCommandOutputEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedCommandOutputEntry }));
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
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isFactsEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedCommandEntry }));
}

export function isContentMatchEntry(value: unknown): value is ParsedContentMatchEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as ParsedContentMatchEntry).kind === "content_match_result"
  );
}

export function getContentMatchEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedContentMatchEntry }> {
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isContentMatchEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedContentMatchEntry }));
}

export function isMembershipEntry(value: unknown): value is ParsedMembershipEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as ParsedMembershipEntry).kind === "membership_result"
  );
}

export function getMembershipEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedMembershipEntry }> {
  return flattenParsedEntries(parsed)
    .filter(({ value }) => isMembershipEntry(value))
    .map(({ key, value }) => ({ key, entry: value as ParsedMembershipEntry }));
}
