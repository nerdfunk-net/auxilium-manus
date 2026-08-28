"use client";

import { useMutation } from "@tanstack/react-query";

import type { WorkflowGitDiffResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";

export function useWorkflowGitDiffMutation(workflowId: number | null) {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: ({ commitA, commitB }: { commitA: string; commitB: string }) =>
      apiCall<WorkflowGitDiffResponse>(`workflows/${workflowId}/version-control/diff`, {
        method: "POST",
        body: JSON.stringify({ commit_a: commitA, commit_b: commitB }),
      }),
  });
}
