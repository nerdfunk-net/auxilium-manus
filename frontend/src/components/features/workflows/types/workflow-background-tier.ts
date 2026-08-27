export interface WorkflowBackgroundTier {
  id: number;
  uuid: string;
  workflow_id: number;
  hatchet_workflow_name: string;
  concurrency_limit: number | null;
  published_by_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowBackgroundTierUpsert {
  concurrency_limit?: number | null;
}
