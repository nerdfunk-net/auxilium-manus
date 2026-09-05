import type { QueryClient } from "@tanstack/react-query";

import type { Template, TemplateListItem } from "@/components/features/templates/types";
import { queryKeys } from "@/lib/query-keys";

import type { WorkflowExportFile } from "../types/workflow-export";
import type {
  WorkflowNotesResponse,
  WorkflowResponse,
} from "../types/workflow-persistence";
import {
  applyCredentialRemap,
  applyTemplateIdRemap,
  resolveWorkflowTemplatesOnImport,
} from "../utils/workflow-import";
import type { WorkflowImportFormValues } from "./workflow-import-schema";

interface WorkflowImportSavePayload {
  name: string;
  description?: string;
  folder: string;
  visibility: WorkflowImportFormValues["visibility"];
  canvas_nodes: WorkflowExportFile["canvas_nodes"];
  canvas_edges: WorkflowExportFile["canvas_edges"];
  canvas_groups: WorkflowExportFile["canvas_groups"];
  static_attributes: WorkflowExportFile["static_attributes"];
}

interface ExecuteWorkflowImportSaveArgs {
  importFile: WorkflowExportFile;
  values: WorkflowImportFormValues;
  overwriteId?: number;
  existingTemplates: TemplateListItem[];
  templatesToCreateCount: number;
  credentialRemap: Map<string, string>;
  apiCall: <T>(path: string, init?: RequestInit) => Promise<T>;
  queryClient: QueryClient;
  createWorkflow: (payload: WorkflowImportSavePayload) => Promise<WorkflowResponse>;
  updateWorkflow: (args: {
    id: number;
    data: WorkflowImportSavePayload;
  }) => Promise<WorkflowResponse>;
}

export async function executeWorkflowImportSave({
  importFile,
  values,
  overwriteId,
  existingTemplates,
  templatesToCreateCount,
  credentialRemap,
  apiCall,
  queryClient,
  createWorkflow,
  updateWorkflow,
}: ExecuteWorkflowImportSaveArgs): Promise<void> {
  const templateIdRemap = await resolveWorkflowTemplatesOnImport({
    exportedTemplates: importFile.templates,
    existingTemplates,
    createTemplate: (payload) =>
      apiCall<Template>("templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
  });

  if (templatesToCreateCount > 0) {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.templates.all,
    });
  }

  let canvasNodes = applyCredentialRemap(importFile.canvas_nodes, credentialRemap);
  canvasNodes = applyTemplateIdRemap(canvasNodes, templateIdRemap);

  const payload: WorkflowImportSavePayload = {
    name: values.name,
    description: values.description,
    folder: values.folder || "/",
    visibility: values.visibility,
    canvas_nodes: canvasNodes,
    canvas_edges: importFile.canvas_edges,
    canvas_groups: importFile.canvas_groups,
    static_attributes: importFile.static_attributes,
  };

  const workflow =
    overwriteId !== undefined
      ? await updateWorkflow({ id: overwriteId, data: payload })
      : await createWorkflow(payload);

  // Notes live outside WorkflowCreate/WorkflowUpdate (see WorkflowNotesUpdate
  // in backend/models/workflows.py) — set via the dedicated endpoint. The
  // wiki's Changes audit trail is intentionally never touched by import.
  await apiCall<WorkflowNotesResponse>(`workflows/${workflow.id}/notes`, {
    method: "PATCH",
    body: JSON.stringify({ notes: importFile.notes }),
  });
  await queryClient.invalidateQueries({
    queryKey: queryKeys.workflows.detail(workflow.id),
  });
}
