"use client";

import { useQuery } from "@tanstack/react-query";

import type { BatfishSnapshotDevicesResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Devices (and their IP addresses) of one snapshot. Needs sources.batfish:query. */
export function useBatfishSnapshotDevicesQuery(
  sourceId: string,
  network: string,
  snapshot: string,
  enabled = true,
) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesBatfish.devices(sourceId, network, snapshot),
    queryFn: async () =>
      apiCall<BatfishSnapshotDevicesResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks/` +
          `${encodeURIComponent(network)}/snapshots/${encodeURIComponent(snapshot)}/devices`,
        { method: "GET" },
      ),
    enabled: enabled && Boolean(sourceId) && Boolean(network) && Boolean(snapshot),
    staleTime: 30 * 1000,
  });
}
