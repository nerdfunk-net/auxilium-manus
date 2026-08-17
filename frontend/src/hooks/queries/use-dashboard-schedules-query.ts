"use client";

import { useQuery } from "@tanstack/react-query";

import type { DashboardScheduleListResponse } from "@/components/features/dashboard/types/dashboard-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useDashboardSchedulesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.dashboard.schedules(),
    queryFn: () =>
      apiCall<DashboardScheduleListResponse>("dashboard/schedules", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
