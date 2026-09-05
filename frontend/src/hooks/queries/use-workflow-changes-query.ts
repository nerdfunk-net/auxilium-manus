"use client";

import { useQuery } from "@tanstack/react-query";

import type { WorkflowChangeListResponse } from "@/components/features/workflows/types/workflow-persistence";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseWorkflowChangesQueryOptions {
  workflowId: number | null;
  enabled?: boolean;
}

export function useWorkflowChangesQuery({
  workflowId,
  enabled = true,
}: UseWorkflowChangesQueryOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.workflows.changes(workflowId ?? 0),
    queryFn: () => apiCall<WorkflowChangeListResponse>(`workflows/${workflowId}/changes`),
    enabled: enabled && workflowId != null,
    staleTime: 10 * 1000,
  });
}
