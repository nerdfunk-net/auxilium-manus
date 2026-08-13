"use client";

import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

export interface HatchetStatusData {
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
  reachable: boolean;
  message: string;
  checked_at: string;
}

export function useHatchetSettingsMutations() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  const testConnection = useMutation<HatchetStatusData, Error>({
    mutationFn: () => apiCall("hatchet/test", { method: "POST" }),
    onError: (error: Error) => {
      toast({
        title: "Connection test failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return useMemo(
    () => ({ testConnection }),
    [testConnection],
  );
}
