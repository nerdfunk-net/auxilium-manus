"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface GeneralSettingsData {
  session_timeout_minutes: number;
  default_export_directory: string;
  switch_to_runs_on_start: boolean;
  resolved_export_directory: string;
}

export function useGeneralSettingsQuery() {
  const { apiCall } = useApi();
  return useQuery<GeneralSettingsData>({
    queryKey: queryKeys.general.settings(),
    queryFn: () => apiCall("general/settings", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}
