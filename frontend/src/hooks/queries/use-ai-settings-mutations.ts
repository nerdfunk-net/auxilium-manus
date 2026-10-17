"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  AiConnectionTestResult,
  AiSettings,
  AiSettingsUpdate,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useAiSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveSettings = useMutation({
    mutationFn: (data: AiSettingsUpdate) =>
      apiCall<AiSettings>("ai/settings", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.ai.settings(), saved);
      // The status drives whether every assistant surface renders, so refresh it now.
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const testConnection = useMutation({
    mutationFn: () => apiCall<AiConnectionTestResult>("ai/settings/test", { method: "POST" }),
    onSuccess: (result) => {
      toast(
        result.ok
          ? { title: "Connection works", description: "The provider accepted the key and model." }
          : {
              title: "Connection failed",
              description: result.message ?? "The provider rejected the request.",
              variant: "destructive",
            },
      );
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(() => ({ saveSettings, testConnection }), [saveSettings, testConnection]);
}
