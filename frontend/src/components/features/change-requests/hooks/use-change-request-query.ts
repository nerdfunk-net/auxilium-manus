"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { ChangeRequestDetail } from "../types/change-request";

const DEPLOYING_POLL_INTERVAL_MS = 2000;

export function useChangeRequestQuery(changeRequestId: number | null) {
  const { apiCall } = useApi();

  return useQuery<ChangeRequestDetail>({
    queryKey: changeRequestId
      ? queryKeys.changeRequests.detail(changeRequestId)
      : ["change-requests", "disabled"],
    queryFn: () =>
      apiCall(`change-requests/${changeRequestId}`, { method: "GET" }),
    enabled: changeRequestId != null,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as ChangeRequestDetail | undefined;
      return data?.status === "deploying" ? DEPLOYING_POLL_INTERVAL_MS : false;
    },
  });
}
