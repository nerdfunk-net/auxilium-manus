"use client";

import { useQuery } from "@tanstack/react-query";

import type { DashboardNotificationListResponse } from "@/components/features/dashboard/types/dashboard-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const DEFAULT_LIMIT = 10;

export function useDashboardNotificationsQuery(limit: number = DEFAULT_LIMIT) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.dashboard.notifications(limit),
    queryFn: () =>
      apiCall<DashboardNotificationListResponse>(`dashboard/notifications?limit=${limit}`, {
        method: "GET",
      }),
    staleTime: 30 * 1000,
  });
}
