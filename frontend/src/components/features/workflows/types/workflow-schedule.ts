export type WorkflowScheduleType = "cron" | "once";

export interface WorkflowSchedule {
  id: number;
  uuid: string;
  workflow_id: number;
  schedule_type: WorkflowScheduleType;
  cron_expression: string | null;
  run_at: string | null;
  enabled: boolean;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowScheduleUpsert {
  schedule_type: WorkflowScheduleType;
  cron_expression?: string | null;
  run_at?: string | null;
  enabled: boolean;
}
