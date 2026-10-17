"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { WorkflowNotesResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowNotesMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notes: string | null) =>
      apiCall<WorkflowNotesResponse>(`workflows/${workflowId}/notes`, {
        method: "PATCH",
        body: JSON.stringify({ notes }),
      }),
    onSuccess: () => {
      if (workflowId == null) return;
      // Mark the workflow's cached detail stale so a reload shows the saved notes, but do not
      // refetch it now: that query also rehydrates the open canvas and would overwrite unsaved
      // edits (see queryKeys.workflows.detail).
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflows.detail(workflowId),
        refetchType: "none",
      });
    },
  });
}
