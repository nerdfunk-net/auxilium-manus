"use client";

import { useQuery } from "@tanstack/react-query";

import type { ISESourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useISESourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesIse.list(),
    queryFn: async () =>
      apiCall<ISESourceListResponse>("sources/ise", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
