"use client";

import { useQuery } from "@tanstack/react-query";

import type { BatfishSnapshotsResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Lists every snapshot in one network on the given Batfish source, sorted
 * most-recent-first. */
export function useBatfishSnapshotsQuery(sourceId: string, network: string) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesBatfish.snapshots(sourceId, network),
    queryFn: async () =>
      apiCall<BatfishSnapshotsResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks/` +
          `${encodeURIComponent(network)}/snapshots`,
        { method: "GET" },
      ),
    enabled: Boolean(sourceId) && Boolean(network),
    staleTime: 30 * 1000,
  });
}
