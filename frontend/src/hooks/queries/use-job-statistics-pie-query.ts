"use client";

import { useQuery } from "@tanstack/react-query";

import type { JobStatisticsPieResponse } from "@/components/features/dashboard/types/statistics-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useJobStatisticsPieQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.statistics.pie(workflowId ?? -1),
    queryFn: () =>
      apiCall<JobStatisticsPieResponse>(`statistics/jobs/${workflowId}/pie`, {
        method: "GET",
      }),
    enabled: workflowId !== null,
    staleTime: 30 * 1000,
  });
}
