"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  CatalystCenterSourceCreatePayload,
  CatalystCenterSourceResponse,
  CatalystCenterSourceUpdatePayload,
  CatalystCenterTestConnectionResponse,
  SourceTestConnectionPayload,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useCatalystCenterSourcesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.sourcesCatalystCenter.all,
    });

  const createSource = useMutation({
    mutationFn: (data: CatalystCenterSourceCreatePayload) =>
      apiCall<CatalystCenterSourceResponse>("sources/catalyst_center", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({
        title: "Saved",
        description: "Catalyst Center source created.",
      });
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
      data: CatalystCenterSourceUpdatePayload;
    }) =>
      apiCall<CatalystCenterSourceResponse>(
        `sources/catalyst_center/${encodeURIComponent(sourceId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      ),
    onSuccess: () => {
      invalidate();
      toast({
        title: "Saved",
        description: "Catalyst Center source updated.",
      });
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
      apiCall<void>(`sources/catalyst_center/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      invalidate();
      toast({
        title: "Removed",
        description: "Catalyst Center source deleted.",
      });
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
    mutationFn: (payload: SourceTestConnectionPayload) =>
      apiCall<CatalystCenterTestConnectionResponse>(
        "sources/catalyst_center/test-connection",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      ),
    onSuccess: (data) => {
      const version = data.release ? ` (reported version ${data.release})` : "";
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
