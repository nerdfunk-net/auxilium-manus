"use client";

import { useQuery } from "@tanstack/react-query";

import type { AiStatus } from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useAiStatusQuery() {
  const { apiCall } = useApi();
  return useQuery<AiStatus>({
    queryKey: queryKeys.ai.status(),
    queryFn: () => apiCall<AiStatus>("ai/status", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
