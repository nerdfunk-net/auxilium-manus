import type { TemplateExportPayload } from "@/components/features/templates/types/template-export";

import type { StaticAttributeDef, WorkflowVisibility } from "./workflow-persistence";

export const WORKFLOW_EXPORT_FORMAT = "auxilium-workflow-v1" as const;

export type WorkflowExportCredentialVisibility = "global" | "private";

export interface WorkflowExportCredentialRef {
  name: string;
  visibility: WorkflowExportCredentialVisibility;
  /** App username of the private credential owner; null for global. */
  owner_username: string | null;
}

/** Full template body plus source-system id for remapping canvas template_id. */
export interface WorkflowExportTemplate extends TemplateExportPayload {
  id: number;
}

export interface WorkflowExportFile {
  export_format: typeof WORKFLOW_EXPORT_FORMAT;
  exported_at: string;
  name: string;
  description: string | null;
  folder: string | null;
  visibility: WorkflowVisibility;
  /** Wiki markdown notes only — the wiki's Changes audit trail is never exported. */
  notes: string | null;
  canvas_nodes: Record<string, unknown>[];
  canvas_edges: Record<string, unknown>[];
  canvas_groups: Record<string, unknown>[];
  static_attributes: StaticAttributeDef[];
  credential_references: WorkflowExportCredentialRef[];
  templates: WorkflowExportTemplate[];
}
