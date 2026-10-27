"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  GlossaryTerm,
  GlossaryTermInput,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

interface UpdateArgs {
  id: number;
  data: GlossaryTermInput;
}

export function useAiGlossaryMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.ai.glossary() });
  const onError = (error: Error) =>
    toast({
      title: "Error",
      description: error.message,
      variant: "destructive",
    });
  const onSaved = (saved: GlossaryTerm) => {
    invalidate();
    toast({
      title: "Glossary term saved",
      description:
        saved.warnings.length > 0
          ? saved.warnings.join(" ")
          : "The assistant can use it from the next request.",
    });
  };

  const createTerm = useMutation({
    mutationFn: (data: GlossaryTermInput) =>
      apiCall<GlossaryTerm>("ai/glossary", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: onSaved,
    onError,
  });

  const updateTerm = useMutation({
    mutationFn: ({ id, data }: UpdateArgs) =>
      apiCall<GlossaryTerm>(`ai/glossary/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: onSaved,
    onError,
  });

  const deleteTerm = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`ai/glossary/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({
        title: "Glossary term deleted",
        description: "The assistant no longer knows this word.",
      });
    },
    onError,
  });

  return useMemo(
    () => ({ createTerm, updateTerm, deleteTerm }),
    [createTerm, updateTerm, deleteTerm],
  );
}
