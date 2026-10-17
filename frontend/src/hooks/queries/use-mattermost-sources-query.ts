"use client";

import { useQuery } from "@tanstack/react-query";

import type { MattermostSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useMattermostSourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesMattermost.list(),
    queryFn: async () =>
      apiCall<MattermostSourceListResponse>("sources/mattermost", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
