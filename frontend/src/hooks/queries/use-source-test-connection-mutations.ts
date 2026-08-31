"use client";

import { useMutation } from "@tanstack/react-query";

import type { SourceTestConnectionResponse } from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

export interface NautobotTestConnectionPayload {
  url?: string;
  credential_id?: number;
  verify_ssl: boolean;
  source_id?: string;
}

export function useNautobotTestConnectionMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();

  return useMutation({
    mutationFn: (payload: NautobotTestConnectionPayload) =>
      apiCall<SourceTestConnectionResponse>("sources/nautobot/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      toast({
        title: data.success ? "Connection successful" : "Connection failed",
        description: data.message,
        variant: data.success ? "default" : "destructive",
      });
    },
    onError: (error: Error) => {
      toast({
        title: "Connection failed",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
