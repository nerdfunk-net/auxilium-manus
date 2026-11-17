"use client";

import { useQuery } from "@tanstack/react-query";

import type { BatfishNetworkSummariesResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Every network of a Batfish source with its snapshot count (Manage dialog). */
export function useBatfishNetworkSummariesQuery(
  sourceId: string,
  enabled = true,
) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesBatfish.networkSummaries(sourceId),
    queryFn: async () =>
      apiCall<BatfishNetworkSummariesResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks-summary`,
        { method: "GET" },
      ),
    enabled: enabled && Boolean(sourceId),
    staleTime: 0,
  });
}
