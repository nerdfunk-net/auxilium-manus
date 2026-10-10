"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  ConversationScope,
  SavedConversationSummary,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useAiConversationsQuery(
  scope: ConversationScope | undefined,
  enabled = true,
) {
  const { apiCall } = useApi();
  return useQuery<SavedConversationSummary[]>({
    queryKey: queryKeys.ai.conversationList(
      scope?.surface ?? "",
      scope?.subjectKey ?? "",
    ),
    queryFn: () => {
      const params = new URLSearchParams({
        surface: scope?.surface ?? "",
        subject_key: scope?.subjectKey ?? "",
      });
      return apiCall<SavedConversationSummary[]>(
        `ai/conversations?${params.toString()}`,
        { method: "GET" },
      );
    },
    enabled: enabled && scope !== undefined,
    staleTime: 30 * 1000,
  });
}
