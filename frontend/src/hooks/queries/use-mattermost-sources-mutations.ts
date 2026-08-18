"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  MattermostSourceCreatePayload,
  MattermostSourceResponse,
  MattermostSourceUpdatePayload,
  MattermostTestConnectionResponse,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useMattermostSourcesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.sourcesMattermost.all });

  const createSource = useMutation({
    mutationFn: (data: MattermostSourceCreatePayload) =>
      apiCall<MattermostSourceResponse>("sources/mattermost", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Mattermost source created." });
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
      data: MattermostSourceUpdatePayload;
    }) =>
      apiCall<MattermostSourceResponse>(
        `sources/mattermost/${encodeURIComponent(sourceId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      ),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Mattermost source updated." });
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
      apiCall<void>(`sources/mattermost/${encodeURIComponent(sourceId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Mattermost source deleted." });
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
    mutationFn: (sourceId: string) =>
      apiCall<MattermostTestConnectionResponse>(
        `sources/mattermost/${encodeURIComponent(sourceId)}/test-connection`,
        { method: "POST" },
      ),
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
