"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { WorkflowResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowGitRestoreMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (commitSha: string) =>
      apiCall<WorkflowResponse>(`workflows/${workflowId}/version-control/restore`, {
        method: "POST",
        body: JSON.stringify({ commit_sha: commitSha }),
      }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.list() });
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.detail(updated.id) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.workflowVersionControl.history(updated.id),
      });
    },
  });
}
