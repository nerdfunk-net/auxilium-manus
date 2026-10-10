/** Workflow envelope types — keep in sync with backend/models/workflow_context.py */

import type { Capability } from "@/lib/capability-types";

export type DeviceStatus = "pending" | "ok" | "failed" | "skipped";

export interface ArtifactRef {
  artifact_id: string;
  kind: string;
  media_type: string;
  size_bytes: number | null;
  sha256: string | null;
  created_at: string;
}

/** Structured, non-sensitive cause of a failure (backend `models/failure.py`). */
export interface FailureInfo {
  phase: string;
  kind: string;
  retryable?: boolean;
  attempts?: number;
  max_attempts?: number;
  elapsed_ms?: number;
  http_status?: number;
  line?: number;
  exception_type?: string;
  hint?: string;
}

export interface DeviceError {
  node_id: string;
  step_id: string;
  code: string;
  message: string;
  occurred_at: string;
  failure?: FailureInfo;
}

export interface CommandResult {
  node_id: string;
  command: string;
  success: boolean;
  executed_at: string;
  output_ref: ArtifactRef | null;
  summary: string | null;
}

/** One outbound API call a step made for a device (detail view only). */
export interface RequestRecord {
  target: string;
  method: string;
  endpoint: string;
  request: Record<string, unknown> | null;
  response: Record<string, unknown> | null;
  ok: boolean;
  sent_at: string;
}

export interface DeviceContext {
  id: string;
  name: string;
  hostname: string;
  platform: string | null;
  network_driver: string | null;
  primary_ip4: string | null;
  source: string;
  source_id: string;
  attribute_bags: Record<string, Record<string, unknown>>;
  running_config_ref: ArtifactRef | null;
  startup_config_ref: ArtifactRef | null;
  parsed: Record<string, unknown>;
  command_results: Record<string, CommandResult[]>;
  dry_run_results: Record<string, Record<string, unknown>>;
  /** Keyed by the node id of the step that made the calls. */
  requests?: Record<string, RequestRecord[]>;
  capabilities: Capability[];
  status: DeviceStatus;
  errors: DeviceError[];
}

export interface WorkflowContext {
  run_id: string;
  workflow_id: string;
  schema_version: number;
  devices: Record<string, DeviceContext>;
  pending_commands: Record<string, Record<string, string[]>>;
  metadata: Record<string, unknown>;
}

export interface StepOutcomeEnvelope {
  outcomes: Record<string, WorkflowContext>;
}

export function isStepOutcomeEnvelope(
  output: unknown,
): output is StepOutcomeEnvelope & Record<string, unknown> {
  return (
    typeof output === "object" &&
    output !== null &&
    "outcomes" in output &&
    typeof (output as StepOutcomeEnvelope).outcomes === "object" &&
    (output as StepOutcomeEnvelope).outcomes !== null
  );
}

export function parseStepOutput(
  output: Record<string, unknown> | null,
): StepOutcomeEnvelope | null {
  if (!isStepOutcomeEnvelope(output)) {
    return null;
  }
  return output;
}
