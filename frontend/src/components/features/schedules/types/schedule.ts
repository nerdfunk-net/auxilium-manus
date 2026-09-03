export type ScheduleType = "cron" | "once";

export interface WorkflowSchedule {
  id: number;
  uuid: string;
  workflow_id: number;
  workflow_name: string | null;
  name: string | null;
  schedule_type: ScheduleType;
  cron_expression: string | null;
  run_at: string | null;
  enabled: boolean;
  run_inputs: Record<string, unknown>;
  concurrency_limit: number | null;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowScheduleCreate {
  workflow_id: number;
  name?: string | null;
  schedule_type: ScheduleType;
  cron_expression?: string | null;
  run_at?: string | null;
  enabled: boolean;
  run_inputs: Record<string, unknown>;
  concurrency_limit?: number | null;
}

export interface WorkflowScheduleUpdate {
  name?: string | null;
  schedule_type?: ScheduleType;
  cron_expression?: string | null;
  run_at?: string | null;
  enabled?: boolean;
  run_inputs?: Record<string, unknown>;
  concurrency_limit?: number | null;
}
