"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface RedisSettingsData {
  enabled: boolean;
  device_ttl_seconds: number;
  redis_connected: boolean;
}

export interface RedisStatsData {
  connected: boolean;
  overview: Record<string, unknown>;
  performance: Record<string, unknown>;
  namespaces: Record<string, unknown>;
}

export function useRedisSettingsQuery() {
  const { apiCall } = useApi();
  return useQuery<RedisSettingsData>({
    queryKey: queryKeys.redis.settings(),
    queryFn: () => apiCall("cache/settings", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}

export function useRedisStatsQuery() {
  const { apiCall } = useApi();
  return useQuery<RedisStatsData>({
    queryKey: queryKeys.redis.stats(),
    queryFn: () => apiCall("cache/stats", { method: "GET" }),
    staleTime: 10 * 1000,
  });
}
