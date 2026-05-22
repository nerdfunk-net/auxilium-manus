export type WorkflowRunStatus = "pending" | "running" | "success" | "failed" | "cancelled";
export type StepStatus = "pending" | "running" | "success" | "failed" | "skipped";

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
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunSummary {
  id: number;
  uuid: string;
  workflow_id: number;
  triggered_by_id: number | null;
  triggered_by_username: string | null;
  status: WorkflowRunStatus;
  trigger_type: string;
  device_ids: string[] | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  hatchet_run_id: string | null;
  error_message: string | null;
  step_results: WorkflowStepResult[];
}

export interface WorkflowRunListResponse {
  runs: WorkflowRunSummary[];
  total: number;
}

export interface TriggerRunRequest {
  device_ids: string[];
  trigger_type: "manual";
}
