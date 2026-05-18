export type WorkflowVisibility = "public" | "private";

export interface WorkflowCreate {
  name: string;
  description?: string;
  folder?: string;
  visibility: WorkflowVisibility;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
}

export interface WorkflowUpdate {
  name?: string;
  description?: string;
  folder?: string;
  visibility?: WorkflowVisibility;
  canvas_nodes?: Record<string, unknown>[];
  canvas_edges?: Record<string, unknown>[];
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
  created_at: string;
  updated_at: string;
}

export interface WorkflowResponse extends WorkflowSummary {
  canvas_nodes: Record<string, unknown>[] | null;
  canvas_edges: Record<string, unknown>[] | null;
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[];
  total: number;
}

export interface PluginConfigResponse {
  plugin_id: string;
  config: Record<string, unknown>;
}
