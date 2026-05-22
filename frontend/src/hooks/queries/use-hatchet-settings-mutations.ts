"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export interface HatchetSettingsUpdateInput {
  host_port?: string;
  token?: string;
  dashboard_url?: string;
  debug?: boolean;
  worker_name?: string;
  worker_slots?: number;
}

export interface HatchetStatusData {
  reachable: boolean;
  token_configured: boolean;
  host_port: string;
  dashboard_url: string;
  message: string;
  checked_at: string;
}

export function useHatchetSettingsMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const saveSettings = useMutation({
    mutationFn: (data: HatchetSettingsUpdateInput) =>
      apiCall("hatchet/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.hatchet.settings() });
      toast({ title: "Saved", description: "Hatchet settings updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const testConnection = useMutation<HatchetStatusData, Error>({
    mutationFn: () =>
      apiCall("hatchet/test", { method: "POST" }),
    onError: (error: Error) => {
      toast({
        title: "Connection test failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  return { saveSettings, testConnection };
}
