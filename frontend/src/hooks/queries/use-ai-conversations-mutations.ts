"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  ConversationScope,
  SavedConversation,
  SavedMessage,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface SaveConversationInput {
  scope: ConversationScope;
  messages: SavedMessage[];
  /** Set when the chat was saved or resumed before: the save then updates that row. */
  savedId: number | null;
}

export function useAiConversationsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.ai.conversations() });
  const onError = (error: Error) =>
    toast({
      title: "Error",
      description: error.message,
      variant: "destructive",
    });

  const save = useMutation({
    mutationFn: ({ scope, messages, savedId }: SaveConversationInput) =>
      savedId === null
        ? apiCall<SavedConversation>("ai/conversations", {
            method: "POST",
            body: JSON.stringify({
              surface: scope.surface,
              subject_key: scope.subjectKey,
              messages,
            }),
          })
        : apiCall<SavedConversation>(`ai/conversations/${savedId}`, {
            method: "PUT",
            body: JSON.stringify({ messages }),
          }),
    onSuccess: (saved) => {
      invalidate();
      toast({
        title: "Conversation saved",
        description: saved.title,
      });
    },
    onError,
  });

  const load = useMutation({
    mutationFn: (id: number) =>
      apiCall<SavedConversation>(`ai/conversations/${id}`, { method: "GET" }),
    onError,
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`ai/conversations/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
    onError,
  });

  return useMemo(() => ({ save, load, remove }), [save, load, remove]);
}
