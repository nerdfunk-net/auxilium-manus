"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  GlossaryKind,
  GlossaryList,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseAiGlossaryOptions {
  kind: GlossaryKind;
  query: string;
  offset: number;
  limit: number;
  /** Administrator-only endpoint: pass `false` for everyone else or while closed. */
  enabled?: boolean;
}

export function useAiGlossaryQuery({
  kind,
  query,
  offset,
  limit,
  enabled = true,
}: UseAiGlossaryOptions) {
  const { apiCall } = useApi();
  return useQuery<GlossaryList>({
    queryKey: queryKeys.ai.glossaryList(kind, query, offset, limit),
    queryFn: () => {
      const params = new URLSearchParams({
        kind,
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
    // Keep the previous page while searching or paging, but never show another kind's rows.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[3] === kind
        ? keepPreviousData(previous)
        : undefined,
    staleTime: 30 * 1000,
  });
}
