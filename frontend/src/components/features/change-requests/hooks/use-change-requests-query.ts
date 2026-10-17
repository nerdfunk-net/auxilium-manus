"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { ChangeRequestListResponse } from "../types/change-request";

const ACTIVE_POLL_INTERVAL_MS = 4000;

interface UseChangeRequestsQueryOptions {
  statuses?: string[];
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseChangeRequestsQueryOptions = {};

export function useChangeRequestsQuery(
  options: UseChangeRequestsQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { statuses, enabled = true } = options;
  const statusKey = statuses && statuses.length > 0 ? statuses.join(",") : undefined;

  return useQuery({
    queryKey: queryKeys.changeRequests.list(statusKey),
    queryFn: () => {
      const params = new URLSearchParams();
      for (const status of statuses ?? []) params.append("status", status);
      const query = params.toString();
      return apiCall<ChangeRequestListResponse>(
        `change-requests${query ? `?${query}` : ""}`,
        { method: "GET" },
      );
    },
    enabled,
    staleTime: 15 * 1000,
    refetchInterval: (query) => {
      const data = query.state.data as ChangeRequestListResponse | undefined;
      const hasInFlight = data?.items.some((item) => item.status === "deploying");
      return hasInFlight ? ACTIVE_POLL_INTERVAL_MS : false;
    },
  });
}
