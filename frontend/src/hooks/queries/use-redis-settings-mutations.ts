"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface RedisSettingsInput {
  enabled: boolean;
  device_ttl_seconds: number;
  location_ttl_seconds: number;
}

interface CacheClearResponse {
  cleared: number;
}

interface CacheRebuildResponse {
  started: boolean;
  hatchet_run_id: string;
}

// The rebuild runs on the worker; re-read the stats once it has had time to
// reload the devices, so "Cached items" reflects the rebuilt cache.
const REBUILD_STATS_REFRESH_DELAY_MS = 5000;

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

  const rebuildCache = useMutation<CacheRebuildResponse, Error>({
    mutationFn: () => apiCall("cache/rebuild", { method: "POST" }),
    onSuccess: () => {
      toast({
        title: "Cache rebuild started",
        description:
          "All devices are being reloaded from Nautobot in the background. This can take a moment.",
      });
      window.setTimeout(
        () => queryClient.invalidateQueries({ queryKey: queryKeys.redis.stats() }),
        REBUILD_STATS_REFRESH_DELAY_MS,
      );
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return useMemo(
    () => ({ saveSettings, clearCache, rebuildCache }),
    [saveSettings, clearCache, rebuildCache],
  );
}
