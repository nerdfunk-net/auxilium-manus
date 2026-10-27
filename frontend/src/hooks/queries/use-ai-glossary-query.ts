"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { GlossaryList } from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseAiGlossaryOptions {
  query: string;
  offset: number;
  limit: number;
  /** Administrator-only endpoint: pass `false` for everyone else or while closed. */
  enabled?: boolean;
}

export function useAiGlossaryQuery({
  query,
  offset,
  limit,
  enabled = true,
}: UseAiGlossaryOptions) {
  const { apiCall } = useApi();
  return useQuery<GlossaryList>({
    queryKey: queryKeys.ai.glossaryList(query, offset, limit),
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (query) {
        params.set("q", query);
      }
      return apiCall<GlossaryList>(`ai/glossary?${params.toString()}`, {
        method: "GET",
      });
    },
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
  });
}
