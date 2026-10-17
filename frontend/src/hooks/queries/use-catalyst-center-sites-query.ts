"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface CatalystCenterSite {
  id: string;
  name: string;
  name_hierarchy: string;
}

export interface CatalystCenterSiteListResponse {
  sites: CatalystCenterSite[];
  total: number;
}

interface UseCatalystCenterSitesQueryOptions {
  /** Fetch only while the picker is open and a source is chosen. */
  enabled: boolean;
}

/** The sites configured on a Catalyst Center source (for the step's site picker). */
export function useCatalystCenterSitesQuery(
  sourceId: string,
  { enabled }: UseCatalystCenterSitesQueryOptions,
) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesCatalystCenter.sites(sourceId),
    queryFn: async () =>
      apiCall<CatalystCenterSiteListResponse>(
        `sources/catalyst_center/${encodeURIComponent(sourceId)}/sites`,
        { method: "GET" },
      ),
    enabled: enabled && Boolean(sourceId),
    staleTime: 30 * 1000,
  });
}
