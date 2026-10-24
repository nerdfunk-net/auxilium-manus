"use client";

import { useQuery } from "@tanstack/react-query";

import type { AiProxySettings } from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Administrator-only endpoint: pass `enabled=false` for everyone else. */
export function useAiProxyQuery(enabled = true) {
  const { apiCall } = useApi();
  return useQuery<AiProxySettings>({
    queryKey: queryKeys.ai.proxy(),
    queryFn: () => apiCall<AiProxySettings>("ai/proxy", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}
