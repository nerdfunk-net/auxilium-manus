"use client";

import { useQuery } from "@tanstack/react-query";

import type { DashboardLayoutResponse } from "@/components/features/dashboard/types/dashboard-layout-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useDashboardLayoutQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.dashboard.layout(),
    queryFn: () => apiCall<DashboardLayoutResponse>("dashboard/layout", { method: "GET" }),
    staleTime: Infinity,
  });
}
