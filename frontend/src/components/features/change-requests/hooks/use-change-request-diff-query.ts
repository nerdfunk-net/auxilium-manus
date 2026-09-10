"use client";

import { useQuery } from "@tanstack/react-query";

import type { ArtifactContentResponse } from "@/hooks/queries/use-artifact-query";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useChangeRequestDiffQuery(
  changeRequestId: number | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const { apiCall } = useApi();

  return useQuery<ArtifactContentResponse>({
    queryKey: changeRequestId
      ? queryKeys.changeRequests.diff(changeRequestId)
      : ["change-requests", "diff", "disabled"],
    queryFn: () =>
      apiCall(`change-requests/${changeRequestId}/diff`, { method: "GET" }),
    enabled: enabled && changeRequestId != null,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 1000,
    retry: false,
  });
}
