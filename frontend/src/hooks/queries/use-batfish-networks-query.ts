"use client";

import { useQuery } from "@tanstack/react-query";

import type { BatfishNetworksResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Lists every network on the given Batfish source's coordinator. */
export function useBatfishNetworksQuery(sourceId: string) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesBatfish.networks(sourceId),
    queryFn: async () =>
      apiCall<BatfishNetworksResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks`,
        { method: "GET" },
      ),
    enabled: Boolean(sourceId),
    staleTime: 30 * 1000,
  });
}
