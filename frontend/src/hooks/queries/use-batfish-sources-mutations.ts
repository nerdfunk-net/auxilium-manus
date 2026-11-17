"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  BatfishDeleteSnapshotsResponse,
  BatfishSourceCreatePayload,
  BatfishSourceResponse,
  BatfishSourceUpdatePayload,
  BatfishTestConnectionPayload,
  BatfishTestConnectionResponse,
} from "@/components/features/settings/types/settings-api";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

/** The server removes at most this many snapshots per request. */
export const SNAPSHOT_DELETE_BATCH_SIZE = 50;

type ApiCall = ReturnType<typeof useApi>["apiCall"];

/** Deletes in sequential batches and merges the results; a failed batch marks its names failed. */
async function deleteSnapshotsInBatches(
  apiCall: ApiCall,
  sourceId: string,
  network: string,
  snapshots: string[],
): Promise<BatfishDeleteSnapshotsResponse> {
  const result: BatfishDeleteSnapshotsResponse = { deleted: [], failed: [] };
  for (let i = 0; i < snapshots.length; i += SNAPSHOT_DELETE_BATCH_SIZE) {
    const batch = snapshots.slice(i, i + SNAPSHOT_DELETE_BATCH_SIZE);
    try {
      const part = await apiCall<BatfishDeleteSnapshotsResponse>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks/${encodeURIComponent(network)}/snapshots/delete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snapshots: batch }),
        },
      );
      result.deleted.push(...part.deleted);
      result.failed.push(...part.failed);
    } catch (error) {
      // Nothing was deleted yet: surface the error. Otherwise report the rest as failed.
      if (result.deleted.length === 0 && result.failed.length === 0)
        throw error;
      result.failed.push(...snapshots.slice(i));
      break;
    }
  }
  return result;
}

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
      apiCall<BatfishTestConnectionResponse>(
        "sources/batfish/test-connection",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
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

  const deleteNetwork = useMutation({
    mutationFn: ({
      sourceId,
      network,
    }: {
      sourceId: string;
      network: string;
    }) =>
      apiCall<void>(
        `sources/batfish/${encodeURIComponent(sourceId)}/networks/${encodeURIComponent(network)}`,
        { method: "DELETE" },
      ),
    onSuccess: (_data, { network }) => {
      invalidate();
      toast({ title: "Removed", description: `Network "${network}" deleted.` });
    },
    onError: (error: Error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  const deleteSnapshots = useMutation({
    mutationFn: ({
      sourceId,
      network,
      snapshots,
    }: {
      sourceId: string;
      network: string;
      snapshots: string[];
    }) => deleteSnapshotsInBatches(apiCall, sourceId, network, snapshots),
    onSuccess: (data) => {
      invalidate();
      toast({
        title: data.failed.length ? "Partly removed" : "Removed",
        description:
          `${data.deleted.length} snapshot(s) deleted` +
          (data.failed.length
            ? `, ${data.failed.length} could not be deleted.`
            : "."),
        variant: data.failed.length ? "destructive" : "default",
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

  return useMemo(
    () => ({
      createSource,
      updateSource,
      deleteSource,
      testConnection,
      deleteNetwork,
      deleteSnapshots,
    }),
    [
      createSource,
      updateSource,
      deleteSource,
      testConnection,
      deleteNetwork,
      deleteSnapshots,
    ],
  );
}
