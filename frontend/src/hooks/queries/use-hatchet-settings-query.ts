"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface HatchetSettingsData {
  host_port: string;
  dashboard_url: string;
  debug: boolean;
  worker_name: string;
  worker_slots: number;
  token_configured: boolean;
}

export function useHatchetSettingsQuery() {
  const { apiCall } = useApi();

  return useQuery<HatchetSettingsData>({
    queryKey: queryKeys.hatchet.settings(),
    queryFn: () => apiCall("hatchet/settings", { method: "GET" }),
    staleTime: 60 * 1000,
  });
}
