"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  AciSourceCreatePayload,
  AciSourceResponse,
  AciSourceUpdatePayload,
  AciTestConnectionResponse,
  SourceTestConnectionPayload,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useAciSourcesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.sourcesAci.all });

  const onError = (error: Error) => {
    toast({
      title: "Error",
      description: error.message,
      variant: "destructive",
    });
  };

  const createSource = useMutation({
    mutationFn: (data: AciSourceCreatePayload) =>
      apiCall<AciSourceResponse>("sources/aci", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Cisco ACI source created." });
    },
    onError,
  });

  const updateSource = useMutation({
    mutationFn: ({
      sourceId,
      data,
    }: {
      sourceId: string;
      data: AciSourceUpdatePayload;
    }) =>
      apiCall<AciSourceResponse>(
        `sources/aci/${encodeURIComponent(sourceId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      ),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Cisco ACI source updated." });
    },
    onError,
  });

  const deleteSource = useMutation({
    mutationFn: (sourceId: string) =>
      apiCall<void>(`sources/aci/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Cisco ACI source deleted." });
    },
    onError,
  });

  const testConnection = useMutation({
    mutationFn: (payload: SourceTestConnectionPayload) =>
      apiCall<AciTestConnectionResponse>("sources/aci/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      const version = data.version ? ` (APIC version ${data.version})` : "";
      toast({
        title: data.success ? "Connection successful" : "Connection failed",
        description: `${data.message}${data.success ? version : ""}`,
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

  return useMemo(
    () => ({ createSource, updateSource, deleteSource, testConnection }),
    [createSource, updateSource, deleteSource, testConnection],
  );
}
