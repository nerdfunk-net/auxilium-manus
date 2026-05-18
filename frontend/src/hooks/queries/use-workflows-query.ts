"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { WorkflowListResponse } from "@/components/features/workflows/types/workflow-persistence";

export function useWorkflowsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.workflows.list(),
    queryFn: () => apiCall<WorkflowListResponse>("workflows"),
    staleTime: 30 * 1000,
  });
}
