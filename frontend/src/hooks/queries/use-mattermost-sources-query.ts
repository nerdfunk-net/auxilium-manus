"use client";

import { useQuery } from "@tanstack/react-query";

import type { MattermostSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseSourcesQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseSourcesQueryOptions = {};

export function useMattermostSourcesQuery(options: UseSourcesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesMattermost.list(),
    queryFn: async () =>
      apiCall<MattermostSourceListResponse>("sources/mattermost", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}
