"use client";

import { useQuery } from "@tanstack/react-query";

import type { JobStatisticsSummaryListResponse } from "@/components/features/dashboard/types/statistics-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useJobStatisticsJobsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.statistics.jobs(),
    queryFn: () =>
      apiCall<JobStatisticsSummaryListResponse>("statistics/jobs", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
