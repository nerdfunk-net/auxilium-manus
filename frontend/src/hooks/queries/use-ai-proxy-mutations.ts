"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  AiProxySettings,
  AiProxySettingsUpdate,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useAiProxyMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveProxy = useMutation({
    mutationFn: (data: AiProxySettingsUpdate) =>
      apiCall<AiProxySettings>("ai/proxy", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.ai.proxy(), saved);
      toast({ title: "Proxy saved", description: "Applies to the next assistant request." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(() => ({ saveProxy }), [saveProxy]);
}
