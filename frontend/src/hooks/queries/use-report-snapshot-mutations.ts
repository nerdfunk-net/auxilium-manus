"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useReportSnapshotMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const deleteSnapshot = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`reports/snapshots/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.reports.snapshots() });
      // The per-report snapshot count and last-generated time changed.
      queryClient.invalidateQueries({ queryKey: queryKeys.reports.definitions() });
      toast({ title: "Deleted", description: "Snapshot deleted." });
    },
    onError: (error: Error) =>
      toast({ title: "Error", description: error.message, variant: "destructive" }),
  });

  return useMemo(() => ({ deleteSnapshot }), [deleteSnapshot]);
}
