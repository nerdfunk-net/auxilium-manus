"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { WorkflowSchedule } from "../types/schedule";

interface UseSchedulesQueryOptions {
  workflowId?: number;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseSchedulesQueryOptions = {};

export function useSchedulesQuery(options: UseSchedulesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { workflowId, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.schedules.list(workflowId),
    queryFn: () =>
      apiCall<WorkflowSchedule[]>(
        workflowId ? `schedules?workflow_id=${workflowId}` : "schedules",
        { method: "GET" },
      ),
    enabled,
    staleTime: 30 * 1000,
  });
}
