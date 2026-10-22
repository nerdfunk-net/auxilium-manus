"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  AgentSourceListResponse,
  AgentStatusResponse,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseAgentSourcesQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseAgentSourcesQueryOptions = {};

export function useAgentSourcesQuery(options: UseAgentSourcesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesAgent.list(),
    queryFn: async () => apiCall<AgentSourceListResponse>("sources/agent", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}

/** Heartbeat view of one saved agent; polls while the dialog that shows it is open. */
export function useAgentStatusQuery(sourceId: string, options: UseAgentSourcesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesAgent.status(sourceId),
    queryFn: async () =>
      apiCall<AgentStatusResponse>(`sources/agent/${encodeURIComponent(sourceId)}/status`, {
        method: "GET",
      }),
    enabled: enabled && Boolean(sourceId),
    staleTime: 0,
    refetchInterval: 10 * 1000,
  });
}
