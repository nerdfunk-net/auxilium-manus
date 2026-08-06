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
  canvas_groups: Record<string, unknown>[] | null;
  static_attributes: StaticAttributeDef[] | null;
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[];
  total: number;
}

export interface PluginConfigResponse {
  plugin_id: string;
  config: Record<string, unknown>;
}
