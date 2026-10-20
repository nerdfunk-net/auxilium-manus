"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** One Nautobot source as a page may see it: never the token or its credential. */
export interface NautobotConfiguredSource {
  source_id: string;
  url: string;
  token_configured: boolean;
}

interface NautobotConfiguredSourcesResponse {
  sources: NautobotConfiguredSource[];
}

interface UseNautobotConfiguredSourcesOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseNautobotConfiguredSourcesOptions = {};

/**
 * The configured Nautobot sources with URL and readiness. Needs only
 * `sources.nautobot:read` (the permission of every Nautobot page), unlike
 * `GET /settings`, which the viewer role does not hold. The settings form still
 * reads and writes the `sources.nautobot.*` rows itself.
 */
export function useNautobotConfiguredSourcesQuery(
  options: UseNautobotConfiguredSourcesOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesNautobot.configuredSources(),
    queryFn: async () => {
      const response = await apiCall<NautobotConfiguredSourcesResponse>(
        "sources/nautobot/configured-sources",
        { method: "GET" },
      );
      return response.sources;
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
