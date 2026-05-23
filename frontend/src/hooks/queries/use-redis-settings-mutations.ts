"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface RedisSettingsInput {
  enabled: boolean;
  device_ttl_seconds: number;
}

interface CacheClearResponse {
  cleared: number;
}

export function useRedisSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveSettings = useMutation({
    mutationFn: (data: RedisSettingsInput) =>
      apiCall("cache/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.redis.settings() });
      toast({ title: "Saved", description: "Redis cache settings updated." });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const clearCache = useMutation<CacheClearResponse, Error>({
    mutationFn: () => apiCall("cache/clear", { method: "POST" }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.redis.stats() });
      toast({
        title: "Cache cleared",
        description: `${result.cleared} ${result.cleared === 1 ? "entry" : "entries"} removed.`,
      });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return { saveSettings, clearCache };
}
