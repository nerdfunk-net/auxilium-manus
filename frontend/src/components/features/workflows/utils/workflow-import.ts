import {
  WORKFLOW_EXPORT_FORMAT,
  type WorkflowExportFile,
} from "../types/workflow-export";

export class WorkflowImportParseError extends Error {}

const REQUIRED_ARRAY_FIELDS = [
  "canvas_nodes",
  "canvas_edges",
  "canvas_groups",
] as const;

export function parseWorkflowExportFile(raw: unknown): WorkflowExportFile {
  if (typeof raw !== "object" || raw === null) {
    throw new WorkflowImportParseError(
      "File does not contain a valid JSON object.",
    );
  }

  const obj = raw as Record<string, unknown>;

  if (obj.export_format !== WORKFLOW_EXPORT_FORMAT) {
    throw new WorkflowImportParseError(
      "Unrecognized workflow export file. Expected a file exported from this application.",
    );
  }
  if (typeof obj.name !== "string" || obj.name.trim().length === 0) {
    throw new WorkflowImportParseError(
      "Import file is missing a workflow name.",
    );
  }
  for (const field of REQUIRED_ARRAY_FIELDS) {
    if (!Array.isArray(obj[field])) {
      throw new WorkflowImportParseError(
        `Import file is missing or has an invalid "${field}" array.`,
      );
    }
  }

  return {
    export_format: WORKFLOW_EXPORT_FORMAT,
    exported_at:
      typeof obj.exported_at === "string"
        ? obj.exported_at
        : new Date().toISOString(),
    name: obj.name,
    description: typeof obj.description === "string" ? obj.description : null,
    folder: typeof obj.folder === "string" ? obj.folder : null,
    visibility: obj.visibility === "public" ? "public" : "private",
    canvas_nodes: obj.canvas_nodes as Record<string, unknown>[],
    canvas_edges: obj.canvas_edges as Record<string, unknown>[],
    canvas_groups: obj.canvas_groups as Record<string, unknown>[],
  };
}
