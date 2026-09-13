"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  BatfishSourceCreatePayload,
  BatfishSourceResponse,
  BatfishSourceUpdatePayload,
  BatfishTestConnectionPayload,
  BatfishTestConnectionResponse,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useBatfishSourcesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.sourcesBatfish.all });

  const createSource = useMutation({
    mutationFn: (data: BatfishSourceCreatePayload) =>
      apiCall<BatfishSourceResponse>("sources/batfish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Batfish source created." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const updateSource = useMutation({
    mutationFn: ({
      sourceId,
      data,
    }: {
      sourceId: string;
      data: BatfishSourceUpdatePayload;
    }) =>
      apiCall<BatfishSourceResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      ),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Batfish source updated." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const deleteSource = useMutation({
    mutationFn: (sourceId: string) =>
      apiCall<void>(`sources/batfish/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Batfish source deleted." });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const testConnection = useMutation({
    mutationFn: (payload: BatfishTestConnectionPayload) =>
      apiCall<BatfishTestConnectionResponse>("sources/batfish/test-connection", {
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

  return useMemo(
    () => ({ createSource, updateSource, deleteSource, testConnection }),
    [createSource, updateSource, deleteSource, testConnection],
  );
}
