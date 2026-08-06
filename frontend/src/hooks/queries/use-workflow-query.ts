"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { WorkflowResponse } from "@/components/features/workflows/types/workflow-persistence";

export function useWorkflowQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.workflows.detail(workflowId ?? -1),
    queryFn: () => apiCall<WorkflowResponse>(`workflows/${workflowId}`),
    enabled: workflowId != null,
    staleTime: 30 * 1000,
  });
}
