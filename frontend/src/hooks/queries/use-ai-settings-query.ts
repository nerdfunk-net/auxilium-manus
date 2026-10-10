"use client";

import { useQuery } from "@tanstack/react-query";

import type { AiSettings } from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useAiSettingsQuery(enabled = true) {
  const { apiCall } = useApi();
  return useQuery<AiSettings>({
    queryKey: queryKeys.ai.settings(),
    queryFn: () => apiCall<AiSettings>("ai/settings", { method: "GET" }),
    enabled,
    staleTime: 30 * 1000,
  });
}
