"use client";

import { useQuery } from "@tanstack/react-query";

import type { PyATSSourceListResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseSourcesQueryOptions {
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseSourcesQueryOptions = {};

export function usePyATSSourcesQuery(options: UseSourcesQueryOptions = DEFAULT_OPTIONS) {
  const { apiCall } = useApi();
  const { enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.sourcesPyats.list(),
    queryFn: async () =>
      apiCall<PyATSSourceListResponse>("sources/pyats", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}
