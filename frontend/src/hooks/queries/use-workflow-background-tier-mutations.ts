"use client";

import { useCallback, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  WorkflowBackgroundTier,
  WorkflowBackgroundTierUpsert,
} from "@/components/features/workflows/types/workflow-background-tier";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowBackgroundTierMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const publish = useMutation({
    mutationFn: ({
      workflowId,
      data,
    }: {
      workflowId: number;
      data: WorkflowBackgroundTierUpsert;
    }) =>
      apiCall<WorkflowBackgroundTier>(`workflows/${workflowId}/background-tier`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.workflows.backgroundTier(updated.workflow_id), updated);
    },
  });

  const unpublish = useMutation({
    mutationFn: (workflowId: number) =>
      apiCall<void>(`workflows/${workflowId}/background-tier`, { method: "DELETE" }),
    onSuccess: (_data, workflowId) => {
      queryClient.setQueryData(queryKeys.workflows.backgroundTier(workflowId), null);
    },
  });

  const checkHasActiveRuns = useCallback(
    (workflowId: number) =>
      apiCall<boolean>(`workflows/${workflowId}/background-tier/has-active-runs`, {
        method: "GET",
      }),
    [apiCall],
  );

  return useMemo(
    () => ({ publish, unpublish, checkHasActiveRuns }),
    [publish, unpublish, checkHasActiveRuns],
  );
}
