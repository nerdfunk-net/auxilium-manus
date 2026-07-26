"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import type { WorkflowResponse } from "@/components/features/workflows/types/workflow-persistence";
import {
  WORKFLOW_EXPORT_FORMAT,
  type WorkflowExportFile,
} from "@/components/features/workflows/types/workflow-export";
import { slugifyWorkflowName } from "@/components/features/workflows/utils/workflow-export";

export function useWorkflowExportMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: async (workflowId: number) => {
      const wf = await apiCall<WorkflowResponse>(`workflows/${workflowId}`);

      const envelope: WorkflowExportFile = {
        export_format: WORKFLOW_EXPORT_FORMAT,
        exported_at: new Date().toISOString(),
        name: wf.name,
        description: wf.description,
        folder: wf.folder,
        visibility: wf.visibility,
        canvas_nodes: wf.canvas_nodes ?? [],
        canvas_edges: wf.canvas_edges ?? [],
        canvas_groups: wf.canvas_groups ?? [],
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
