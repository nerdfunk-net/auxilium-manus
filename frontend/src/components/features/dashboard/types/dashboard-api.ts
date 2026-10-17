import type { WorkflowVisibility } from "@/components/features/workflows/types/workflow-persistence";

export type ScheduleType = "cron" | "once";

export interface DashboardScheduleItem {
  schedule_id: number;
  workflow_id: number;
  workflow_name: string;
  workflow_visibility: WorkflowVisibility;
  schedule_type: ScheduleType;
  cron_expression: string | null;
  run_at: string | null;
  next_run_at: string | null;
  last_triggered_at: string | null;
}

export interface DashboardScheduleListResponse {
  schedules: DashboardScheduleItem[];
}

export interface DashboardRunItem {
  run_id: number;
  workflow_id: number;
  workflow_name: string;
  status: string;
  trigger_type: string;
  triggered_by_username: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface DashboardRecentRunsResponse {
  runs: DashboardRunItem[];
}

export interface DashboardNotificationItem {
  id: number;
  run_id: number;
  workflow_id: number;
  workflow_name: string;
  workflow_owner_username: string | null;
  device_name: string | null;
  severity: string;
  message: string;
  created_at: string;
}

export interface DashboardNotificationListResponse {
  notifications: DashboardNotificationItem[];
}
