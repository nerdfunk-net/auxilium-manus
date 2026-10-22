"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  AgentSourceCreatePayload,
  AgentSourceResponse,
  AgentSourceUpdatePayload,
  AgentTestConnectionPayload,
  AgentTestConnectionResponse,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

const JSON_HEADERS = { "Content-Type": "application/json" };

export function useAgentSourcesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.sourcesAgent.all });
  const reportError = (error: Error) =>
    toast({ title: "Error", description: error.message, variant: "destructive" });

  const createSource = useMutation({
    mutationFn: (data: AgentSourceCreatePayload) =>
      apiCall<AgentSourceResponse>("sources/agent", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Agent source created." });
    },
    onError: reportError,
  });

  const updateSource = useMutation({
    mutationFn: ({ sourceId, data }: { sourceId: string; data: AgentSourceUpdatePayload }) =>
      apiCall<AgentSourceResponse>(`sources/agent/${encodeURIComponent(sourceId)}`, {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Saved", description: "Agent source updated." });
    },
    onError: reportError,
  });

  const deleteSource = useMutation({
    mutationFn: (sourceId: string) =>
      apiCall<void>(`sources/agent/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Removed", description: "Agent source deleted." });
    },
    onError: reportError,
  });

  const testConnection = useMutation({
    mutationFn: (payload: AgentTestConnectionPayload) =>
      apiCall<AgentTestConnectionResponse>("sources/agent/test-connection", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      toast({
        title: data.success ? "Connection successful" : "Connection failed",
        description:
          data.success && data.latency_ms != null
            ? `${data.message} (${data.latency_ms} ms)`
            : data.message,
        variant: data.success ? "default" : "destructive",
      });
    },
    onError: (error: Error) =>
      toast({ title: "Connection failed", description: error.message, variant: "destructive" }),
    // The status panel polls; refresh it now so it cannot keep saying "Offline" next to a toast
    // that says the agent answered.
    onSettled: (_data, _error, variables) =>
      queryClient.invalidateQueries({
        queryKey: queryKeys.sourcesAgent.status(variables.source_id),
      }),
  });

  return useMemo(
    () => ({ createSource, updateSource, deleteSource, testConnection }),
    [createSource, updateSource, deleteSource, testConnection],
  );
}
