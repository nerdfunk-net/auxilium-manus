"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  WorkflowAiRelease,
  WorkflowAiReleaseRequest,
} from "@/components/features/workflows/types/workflow-ai-release";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowAiReleaseMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const release = useMutation({
    mutationFn: ({
      workflowId,
      data,
    }: {
      workflowId: number;
      data: WorkflowAiReleaseRequest;
    }) =>
      apiCall<WorkflowAiRelease>(`workflows/${workflowId}/ai-release`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (_updated, { workflowId }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.aiRelease(workflowId) });
    },
  });

  const unrelease = useMutation({
    mutationFn: (workflowId: number) =>
      apiCall<WorkflowAiRelease>(`workflows/${workflowId}/ai-release`, { method: "DELETE" }),
    onSuccess: (_updated, workflowId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.aiRelease(workflowId) });
    },
  });

  return useMemo(() => ({ release, unrelease }), [release, unrelease]);
}
