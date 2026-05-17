"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { PluginListResponse } from "@/components/features/workflows/types/plugin-registry";

export function usePluginsQuery() {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.plugins.list(),
    queryFn: () => apiCall<PluginListResponse>("plugins"),
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}
