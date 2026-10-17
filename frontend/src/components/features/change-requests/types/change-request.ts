export type ChangeRequestStatus =
  | "staged"
  | "approved"
  | "deploying"
  | "deployed"
  | "failed"
  | "rejected"
  | "expired";

export const CHANGE_REQUEST_TERMINAL_STATUSES: ReadonlySet<ChangeRequestStatus> = new Set([
  "deployed",
  "failed",
  "rejected",
  "expired",
]);

export interface ChangeRequestDiffStats {
  additions?: number;
  deletions?: number;
  files?: number;
  truncated?: boolean;
}

export interface ChangeRequestSummary {
  id: number;
  uuid: string;
  title: string | null;
  status: ChangeRequestStatus;
  source_workflow_id: number | null;
  source_run_id: number | null;
  deploy_workflow_id: number | null;
  deploy_run_id: number | null;
  branch: string | null;
  commit_sha: string | null;
  diff_stats: ChangeRequestDiffStats | null;
  approved_via: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}

export interface ChangeRequestDetail extends ChangeRequestSummary {
  base_branch: string | null;
  git_repository_id: number | null;
  device_ids: string[];
  run_inputs: Record<string, unknown>;
  diff_artifact_id: string | null;
  deploy_error: string | null;
  reject_reason: string | null;
  approved_by_id: number | null;
  approved_by_username: string | null;
}

export interface ChangeRequestListResponse {
  items: ChangeRequestSummary[];
  total: number;
}
