"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import type { CredentialListResponse } from "@/components/features/settings/credentials/types";
import type { Template } from "@/components/features/templates/types";
import type { WorkflowResponse } from "@/components/features/workflows/types/workflow-persistence";
import {
  WORKFLOW_EXPORT_FORMAT,
  type WorkflowExportFile,
} from "@/components/features/workflows/types/workflow-export";
import {
  buildCredentialExportReferences,
  buildWorkflowExportTemplates,
  collectCredentialReferencesFromCanvas,
  collectTemplateIdsFromCanvas,
  slugifyWorkflowName,
} from "@/components/features/workflows/utils/workflow-export";

export function useWorkflowExportMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (workflowId: number) => {
      const [wf, credentialsResponse] = await Promise.all([
        apiCall<WorkflowResponse>(`workflows/${workflowId}`),
        apiCall<CredentialListResponse>(
          "credentials?source=general&include_expired=true",
          { method: "GET" },
        ),
      ]);

      const canvasNodes = wf.canvas_nodes ?? [];
      const credentialNames = collectCredentialReferencesFromCanvas(canvasNodes);
      const credentialReferences = buildCredentialExportReferences(
        credentialNames,
        credentialsResponse.credentials ?? [],
      );

      const templateIds = collectTemplateIdsFromCanvas(canvasNodes);
      const templates = (
        await Promise.all(
          templateIds.map((id) =>
            apiCall<Template>(`templates/${id}`).catch(() => null),
          ),
        )
      ).filter((template): template is Template => template !== null);

      const envelope: WorkflowExportFile = {
        export_format: WORKFLOW_EXPORT_FORMAT,
        exported_at: new Date().toISOString(),
        name: wf.name,
        description: wf.description,
        folder: wf.folder,
        visibility: wf.visibility,
        canvas_nodes: canvasNodes,
        canvas_edges: wf.canvas_edges ?? [],
        canvas_groups: wf.canvas_groups ?? [],
        credential_references: credentialReferences,
        templates: buildWorkflowExportTemplates(templateIds, templates),
      };

      const blob = new Blob([JSON.stringify(envelope, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${slugifyWorkflowName(wf.name)}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
    onSuccess: () => {
      toast({
        title: "Export complete",
        description: "Workflow JSON was downloaded.",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Export failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
