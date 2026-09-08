import type { ArtifactRef } from "@/lib/workflow-context-types";

export interface DebugLogDeviceEntry {
  device_id: string;
  device_name: string;
  message: string;
}

export interface DebugLogsPayload {
  message?: string;
  logged_at?: string;
  device_count?: number;
  devices: Record<string, DebugLogDeviceEntry>;
}

export interface LogAttributesPayload {
  output_destination?: string;
  output_format?: string;
  filename?: string | null;
  append?: boolean | null;
  file_path?: string | null;
  written_at?: string;
  device_count?: number;
  content?: string;
}

export interface ParsedTemplateEntry {
  artifact_ref: ArtifactRef;
  step_node_id: string;
  output_key: string;
  size_bytes: number;
  kind: string;
}

/**
 * compare-data writes `{ additions, deletions }` (line-diff based); the
 * structure-aware compare-pyats-snapshot writes `{ line_count }` since Genie's
 * str(Diff) line prefixes aren't a reliable +/- signal. Both keys are optional.
 */
export interface ComparisonDiffStats {
  additions?: number;
  deletions?: number;
  line_count?: number;
}

export interface ParsedComparisonResultEntry {
  kind: "comparison_result";
  matched: boolean;
  step_node_id: string;
  reference_path?: string;
  reference_location?: string;
  content_source?: string;
  diff_stats?: ComparisonDiffStats;
  comparison_diff_key?: string;
}

export interface ParsedComparisonDiffEntry {
  kind: "comparison_diff";
  matched: boolean;
  artifact_ref: ArtifactRef;
  /** Full JSON of the live ("current") snapshot side — present for pyATS
   * snapshot comparisons so the detail view can show exactly what differs. */
  live_snapshot_ref?: ArtifactRef;
  /** Full JSON of the reference ("baseline") snapshot side. */
  reference_snapshot_ref?: ArtifactRef;
  step_node_id: string;
  reference_path?: string;
  reference_location?: string;
  content_source?: string;
  diff_stats?: ComparisonDiffStats;
  output_key?: string;
  /** Genie feature name — set by compare-pyats-snapshot's per-feature entries. */
  feature?: string;
}

/**
 * Genie-parsed config output from get-pyats-config / parse-cisco-config:
 * `{"running": <genie dict>|null}` (parse-cisco-config additionally has a
 * `startup` key). Stored inline in `device.parsed` -- unlike templates and
 * comparisons, this is small structured JSON, not an artifact reference.
 */
export interface GenieParsedConfigEntry {
  running?: unknown;
  startup?: unknown;
}

/**
 * Genie "learn" snapshot output from get-pyats-snapshot:
 * `{"kind": "pyats_snapshot", "artifact_ref": ..., "features": {name: {success, error}}}`.
 * The `kind` discriminator keeps this unambiguous from the other `device.parsed`
 * shapes above (comparison entries use the same discriminator convention).
 */
export interface SnapshotFeatureResult {
  success: boolean;
  error?: string | null;
}

export interface SnapshotEntry {
  kind: "pyats_snapshot";
  artifact_ref: ArtifactRef;
  step_node_id: string;
  features: Record<string, SnapshotFeatureResult>;
}

/**
 * Normalized per-command structured output from run-command when its
 * `parser` is "textfsm" or "genie": `{"<command>": {parsed, error}}` at
 * `device.parsed.<parsed_output_key>`. Both parsers write this same shape
 * (see doc/WORKFLOW-STEPS.md "Normalized command-output parsing") so a
 * command that couldn't be parsed carries `error` with `parsed: null`
 * instead of failing the device.
 */
export interface ParsedCommandEntry {
  parsed: unknown;
  error: string | null;
}

export type ParsedCommandOutputEntry = Record<string, ParsedCommandEntry>;
