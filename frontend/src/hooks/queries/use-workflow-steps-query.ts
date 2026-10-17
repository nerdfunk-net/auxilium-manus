"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { PluginListResponse } from "@/components/features/workflows/types/plugin-registry";

export function useWorkflowStepsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.workflowSteps.list(),
    queryFn: () => apiCall<PluginListResponse>("workflow-steps"),
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}
