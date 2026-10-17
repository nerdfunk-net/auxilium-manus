"use client";

import { useQuery } from "@tanstack/react-query";

import type { CatalystCenterSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useCatalystCenterSourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesCatalystCenter.list(),
    queryFn: async () =>
      apiCall<CatalystCenterSourceListResponse>("sources/catalyst_center", {
        method: "GET",
      }),
    staleTime: 30 * 1000,
  });
}
