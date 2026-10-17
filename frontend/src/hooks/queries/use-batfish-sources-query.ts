"use client";

import { useQuery } from "@tanstack/react-query";

import type { BatfishSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useBatfishSourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesBatfish.list(),
    queryFn: async () =>
      apiCall<BatfishSourceListResponse>("sources/batfish", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
