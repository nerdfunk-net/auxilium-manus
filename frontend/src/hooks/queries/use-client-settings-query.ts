"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** The general settings every signed-in user may read (no `general_settings:read` needed). */
export interface ClientSettingsData {
  session_timeout_minutes: number;
  switch_to_runs_on_start: boolean;
}

export function useClientSettingsQuery() {
  const { apiCall } = useApi();
  return useQuery<ClientSettingsData>({
    queryKey: queryKeys.general.clientSettings(),
    queryFn: () => apiCall("general/client-settings", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
