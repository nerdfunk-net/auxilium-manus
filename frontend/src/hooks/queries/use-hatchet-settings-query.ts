"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface HatchetConfigData {
  server_url: string;
  dashboard_url: string;
  host_port: string;
  tenant_id: string;
  namespace: string;
  tls_strategy: string;
  debug: boolean;
  token_configured: boolean;
  worker_name: string;
  worker_slots: number;
  sdk_version: string;
}

export function useHatchetSettingsQuery() {
  const { apiCall } = useApi();

  return useQuery<HatchetConfigData>({
    queryKey: queryKeys.hatchet.settings(),
    queryFn: () => apiCall("hatchet/settings", { method: "GET" }),
    staleTime: 60 * 1000,
  });
}
