export type WorkflowVisibility = "public" | "private";
export type StaticAttributeType = "string" | "number" | "boolean";

/** A run-scoped trigger input declared on a workflow. Resolved values are
 * seeded into every device's attribute_bags["run_input"] at run time — see
 * doc/WORKFLOW-STEPS.md "Static attributes". */
export interface StaticAttributeDef {
  name: string;
  type: StaticAttributeType;
  default?: string | number | boolean;
  required: boolean;
}

export interface WorkflowCreate {
  name: string;
  description?: string;
  folder?: string;
  visibility: WorkflowVisibility;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
  canvas_groups: Record<string, unknown>[];
  static_attributes: StaticAttributeDef[];
  is_version_controlled?: boolean;
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  folder?: string;
  visibility?: WorkflowVisibility;
  canvas_nodes?: Record<string, unknown>[];
  canvas_edges?: Record<string, unknown>[];
  canvas_groups?: Record<string, unknown>[];
  static_attributes?: StaticAttributeDef[];
  is_version_controlled?: boolean;
}

export interface WorkflowSummary {
  id: number;
  uuid: string | null;
  name: string;
  creator_id: number | null;
  creator_username: string | null;
  description: string | null;
  folder: string | null;
  visibility: WorkflowVisibility;
  is_version_controlled: boolean;
  created_at: string;
  updated_at: string;
}

/** Outcome of the best-effort Git sync performed as part of a save — see
 * WorkflowGitSyncStatus in backend/models/workflows.py. */
export interface WorkflowGitSyncStatus {
  status: "ok" | "failed" | "skipped";
  commit_sha: string | null;
  pushed: boolean;
  message: string | null;
}

export interface WorkflowResponse extends WorkflowSummary {
  canvas_nodes: Record<string, unknown>[] | null;
  canvas_edges: Record<string, unknown>[] | null;
  canvas_groups: Record<string, unknown>[] | null;
  static_attributes: StaticAttributeDef[] | null;
  git_sync: WorkflowGitSyncStatus | null;
}

export interface WorkflowGitCommitEntry {
  hash: string;
  short_hash: string;
  message: string;
  author: { name: string; email: string };
  date: string;
  change_type?: string | null;
}

export interface WorkflowGitHistoryResponse {
  commits: WorkflowGitCommitEntry[];
  repository_name: string;
}

export interface WorkflowGitDiffLine {
  line_number: number;
  content: string;
  type: "equal" | "delete" | "insert" | "replace";
}

export interface WorkflowGitDiffResponse {
  diff_lines: string[];
  left_lines: WorkflowGitDiffLine[];
  right_lines: WorkflowGitDiffLine[];
  stats: { additions: number; deletions: number; changes: number; total_lines: number };
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[];
  total: number;
}

export interface PluginConfigResponse {
  plugin_id: string;
  config: Record<string, unknown>;
}
