"use client";

import { useQuery } from "@tanstack/react-query";

import type { AciSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useAciSourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesAci.list(),
    queryFn: async () =>
      apiCall<AciSourceListResponse>("sources/aci", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
