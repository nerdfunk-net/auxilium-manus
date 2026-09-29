export type WorkflowRunStatus =
  | "pending"
  | "running"
  | "paused"
  | "success"
  | "failed"
  | "cancelled";

/** Runs in one of these statuses are finished and eligible for deletion. */
export const TERMINAL_RUN_STATUSES: readonly WorkflowRunStatus[] = [
  "success",
  "failed",
  "cancelled",
];
export type StepStatus = "pending" | "running" | "success" | "partial" | "failed" | "skipped";

/** See backend/models/runs.py::ErrorCategory for the full contract. */
export type ErrorCategory = "configuration" | "execution" | "internal";

/** WorkflowRun.approval_state — see doc/WAIT-AND-RUN.md §5.2. Authored only by
 * the backend orchestrator; the frontend treats it read-only. */
export interface ApprovalState {
  awaiting: boolean;
  next_batch_index: number;
  total_batches: number;
  batches_completed: number;
  devices_total: number;
  devices_completed: number;
  devices_failed: number;
  next_batch_device_names: string[];
  auto_approve_remaining: boolean;
}

export interface WorkflowStepResult {
  id: number;
  run_id: number;
  step_node_id: string;
  step_type: string;
  step_name: string;
  status: StepStatus;
  started_at: string | null;
  finished_at: string | null;
  output: Record<string, unknown> | null;
  error_message: string | null;
  error_category: ErrorCategory | null;
  error_id: string | null;
  created_at: string;
  updated_at: string;
}

export type DeviceGroupStatus = "pending" | "running" | "success" | "partial" | "failed";

/** Per-node state a fan-out child reports while it runs (children write no step rows). */
export type DeviceGroupNodeState = "running" | "success" | "partial" | "failed" | "skipped";

/** Live progress of one fan-out child — see backend core/models/runs.py::WorkflowRunDeviceGroup. */
export interface WorkflowRunDeviceGroup {
  child_index: number;
  device_names: string[];
  status: DeviceGroupStatus;
  node_states: Record<string, string>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export type RunEventLevel = "info" | "warning" | "error";

/** Live event within a running step (connect attempts, retries, failures). */
export interface WorkflowRunEvent {
  id: number;
  step_node_id: string;
  /** Fan-out child that emitted it; null for the parent run's own steps. */
  child_index: number | null;
  device_name: string | null;
  level: RunEventLevel | string;
  kind: string;
  message: string;
  created_at: string;
}

export interface WorkflowRunEventPage {
  events: WorkflowRunEvent[];
  next_after_id: number;
}

export interface WorkflowRunSummary {
  id: number;
  uuid: string;
  workflow_id: number;
  triggered_by_id: number | null;
  triggered_by_username: string | null;
  status: WorkflowRunStatus;
  trigger_type: string;
  current_node_id: string | null;
  debug_message: string | null;
  approval_state: ApprovalState | null;
  device_ids: string[] | null;
  run_inputs: Record<string, string | number | boolean> | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  hatchet_run_id: string | null;
  error_message: string | null;
  error_category: ErrorCategory | null;
  error_id: string | null;
  step_results: WorkflowStepResult[];
  device_groups: WorkflowRunDeviceGroup[];
}

export interface WorkflowRunListResponse {
  runs: WorkflowRunSummary[];
  total: number;
}

export interface TriggerRunRequest {
  device_ids: string[];
  trigger_type: "manual";
  run_inputs?: Record<string, string | number | boolean>;
}
