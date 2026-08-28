"use client";

import { useQuery } from "@tanstack/react-query";

import type { WorkflowGitHistoryResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseWorkflowGitHistoryQueryOptions {
  workflowId: number | null;
  enabled?: boolean;
}

export function useWorkflowGitHistoryQuery({
  workflowId,
  enabled = true,
}: UseWorkflowGitHistoryQueryOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.workflowVersionControl.history(workflowId ?? 0),
    queryFn: () =>
      apiCall<WorkflowGitHistoryResponse>(`workflows/${workflowId}/version-control/history`),
    enabled: enabled && workflowId != null,
    staleTime: 10 * 1000,
  });
}
