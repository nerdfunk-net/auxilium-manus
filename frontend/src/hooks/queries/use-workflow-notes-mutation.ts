"use client";

import { useMutation } from "@tanstack/react-query";

import type { WorkflowNotesResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";

export function useWorkflowNotesMutation(workflowId: number | null) {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: (notes: string | null) =>
      apiCall<WorkflowNotesResponse>(`workflows/${workflowId}/notes`, {
        method: "PATCH",
        body: JSON.stringify({ notes }),
      }),
  });
}
