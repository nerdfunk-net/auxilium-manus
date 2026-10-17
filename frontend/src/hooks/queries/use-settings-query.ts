"use client";

import { useQuery } from "@tanstack/react-query";

import type { SettingListResponse, SettingRecord } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

interface UseSettingsListQueryOptions {
  keyPrefix?: string;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseSettingsListQueryOptions = {};

export function useSettingsListQuery(
  options: UseSettingsListQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { keyPrefix, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.settings.list(keyPrefix),
    queryFn: async () => {
      const params = keyPrefix
        ? `?key_prefix=${encodeURIComponent(keyPrefix)}`
        : "";
      return apiCall<SettingListResponse>(`settings${params}`, { method: "GET" });
    },
    enabled,
    staleTime: 30 * 1000,
  });
}

interface UseSettingQueryOptions {
  key: string;
  enabled?: boolean;
}

export function useSettingQuery({ key, enabled = true }: UseSettingQueryOptions) {
  const { apiCall } = useApi();

  return useQuery({
    queryKey: queryKeys.settings.detail(key),
    queryFn: async () =>
      apiCall<SettingRecord>(`settings/${encodeURIComponent(key)}`, {
        method: "GET",
      }),
    enabled: enabled && Boolean(key),
    staleTime: 30 * 1000,
    retry: (failureCount, error) => {
      if (error instanceof Error && error.message.includes("404")) {
        return false;
      }
      return failureCount < 2;
    },
  });
}
