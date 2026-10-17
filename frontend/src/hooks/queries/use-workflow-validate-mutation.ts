"use client";

import { useMutation } from "@tanstack/react-query";

import type { WorkflowValidationResult } from "@/components/features/workflows/types/workflow-validation";
import { useApi } from "@/hooks/use-api";

interface ValidateDraft {
  canvasNodes: Record<string, unknown>[];
  canvasEdges: Record<string, unknown>[];
}

export function useWorkflowValidateMutation(workflowId: number | null) {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: ({ canvasNodes, canvasEdges }: ValidateDraft) =>
      apiCall<WorkflowValidationResult>(`workflows/${workflowId}/validate`, {
        method: "POST",
        body: JSON.stringify({ canvas_nodes: canvasNodes, canvas_edges: canvasEdges }),
      }),
  });
}
