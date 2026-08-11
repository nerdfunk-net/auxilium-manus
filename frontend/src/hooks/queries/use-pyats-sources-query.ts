"use client";

import { useQuery } from "@tanstack/react-query";

import type { PyATSSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function usePyATSSourcesQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.sourcesPyats.list(),
    queryFn: async () =>
      apiCall<PyATSSourceListResponse>("sources/pyats", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
