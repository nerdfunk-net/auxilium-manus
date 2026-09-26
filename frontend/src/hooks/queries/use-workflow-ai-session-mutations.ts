"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  WorkflowAiSession,
  WorkflowAiSessionEnableRequest,
} from "@/components/features/workflows/types/workflow-ai-session";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowAiSessionMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const enable = useMutation({
    mutationFn: ({
      workflowId,
      data,
    }: {
      workflowId: number;
      data: WorkflowAiSessionEnableRequest;
    }) =>
      apiCall<WorkflowAiSession>(`workflows/${workflowId}/ai-session`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (updated, { workflowId }) => {
      queryClient.setQueryData(queryKeys.workflows.aiSession(workflowId), updated);
    },
  });

  const disable = useMutation({
    mutationFn: (workflowId: number) =>
      apiCall<void>(`workflows/${workflowId}/ai-session`, { method: "DELETE" }),
    onSuccess: (_data, workflowId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.aiSession(workflowId) });
    },
  });

  return useMemo(() => ({ enable, disable }), [enable, disable]);
}
