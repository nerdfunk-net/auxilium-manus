"use client";

import { useQuery } from "@tanstack/react-query";

import type { DashboardRecentRunsResponse } from "@/components/features/dashboard/types/dashboard-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const DEFAULT_LIMIT = 10;

export function useDashboardRecentRunsQuery(limit: number = DEFAULT_LIMIT) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.dashboard.recentRuns(limit),
    queryFn: () =>
      apiCall<DashboardRecentRunsResponse>(`dashboard/recent-runs?limit=${limit}`, {
        method: "GET",
      }),
    staleTime: 30 * 1000,
  });
}
