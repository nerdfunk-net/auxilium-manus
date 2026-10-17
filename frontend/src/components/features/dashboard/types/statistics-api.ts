import type { WorkflowVisibility } from "@/components/features/workflows/types/workflow-persistence";

export interface JobStatisticsSummaryItem {
  workflow_id: number;
  workflow_name: string;
  workflow_visibility: WorkflowVisibility;
  latest_run_id: number;
  latest_run_created_at: string;
  success_count: number;
  failed_count: number;
  total_count: number;
}

export interface JobStatisticsSummaryListResponse {
  jobs: JobStatisticsSummaryItem[];
}

export interface JobStatisticsPieResponse {
  workflow_id: number;
  workflow_name: string;
  run_id: number;
  run_created_at: string;
  success_count: number;
  failed_count: number;
  total_count: number;
}
