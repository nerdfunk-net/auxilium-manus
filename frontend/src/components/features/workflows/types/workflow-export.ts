import type { WorkflowVisibility } from "./workflow-persistence";

export const WORKFLOW_EXPORT_FORMAT = "auxilium-workflow-v1" as const;

export interface WorkflowExportFile {
  export_format: typeof WORKFLOW_EXPORT_FORMAT;
  exported_at: string;
  name: string;
  description: string | null;
  folder: string | null;
  visibility: WorkflowVisibility;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
  canvas_groups: Record<string, unknown>[];
}
