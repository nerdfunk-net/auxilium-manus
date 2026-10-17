"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface IseNetworkDeviceGroup {
  id: string | null;
  name: string;
  description: string | null;
}

export interface IseNetworkDeviceGroupsResponse {
  total: number;
  groups: IseNetworkDeviceGroup[];
  truncated: boolean;
}

interface UseIseNetworkDeviceGroupsQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseIseNetworkDeviceGroupsQueryOptions = {};

/** All Network Device Groups of an ISE source (full `#`-delimited names). */
export function useIseNetworkDeviceGroupsQuery(
  sourceId: string,
  options = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesIse.networkDeviceGroups(sourceId),
    queryFn: async () =>
      apiCall<IseNetworkDeviceGroupsResponse>(
        `sources/ise/${encodeURIComponent(sourceId)}/network-device-groups/all`,
        { method: "GET" },
      ),
    enabled: enabled && Boolean(sourceId),
    // Always refetched when the picker opens: the user has often just
    // created a group in ISE.
    staleTime: 0,
  });
}
