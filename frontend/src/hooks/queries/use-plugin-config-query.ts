"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { PluginConfigResponse } from "@/components/features/workflows/types/workflow-persistence";

export function usePluginConfigQuery(pluginId: string | null) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.pluginConfig.detail(pluginId ?? ""),
    queryFn: () =>
      apiCall<PluginConfigResponse>(
        `workflow-steps/${pluginId}/get-config`,
      ),
    enabled: pluginId !== null && pluginId.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
  });
}
