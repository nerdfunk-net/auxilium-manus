"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import type {
  ReportDefinition,
  ReportDefinitionInput,
  ReportSection,
  ReportSnapshot,
} from "@/components/features/reports/types/report-definition";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

export function useReportDefinitionMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const onError = (error: Error) =>
    toast({ title: "Error", description: error.message, variant: "destructive" });
  const invalidateDefinitions = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.reports.definitions() });

  const createDefinition = useMutation({
    mutationFn: (data: ReportDefinitionInput) =>
      apiCall<ReportDefinition>("reports/definitions", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidateDefinitions();
      toast({ title: "Saved", description: "Report created." });
    },
    onError,
  });

  const updateDefinition = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ReportDefinitionInput> }) =>
      apiCall<ReportDefinition>(`reports/definitions/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidateDefinitions();
      toast({ title: "Saved", description: "Report updated." });
    },
    onError,
  });

  /** Append a section to an existing report (read it, then save it back with the new section). */
  const addSection = useMutation({
    mutationFn: async ({ id, section }: { id: number; section: ReportSection }) => {
      const current = await apiCall<ReportDefinition>(`reports/definitions/${id}`, {
        method: "GET",
      });
      return apiCall<ReportDefinition>(`reports/definitions/${id}`, {
        method: "PUT",
        body: JSON.stringify({ sections: [...current.sections, section] }),
      });
    },
    onSuccess: (definition) => {
      invalidateDefinitions();
      toast({ title: "Section added", description: `Added to “${definition.name}”.` });
    },
    onError,
  });

  const deleteDefinition = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`reports/definitions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidateDefinitions();
      // Its snapshots stay, but no longer belong to a report.
      queryClient.invalidateQueries({ queryKey: queryKeys.reports.snapshots() });
      toast({ title: "Deleted", description: "Report deleted. Its snapshots are kept." });
    },
    onError,
  });

  const generateSnapshot = useMutation({
    mutationFn: (id: number) =>
      apiCall<ReportSnapshot>(`reports/definitions/${id}/generate`, { method: "POST" }),
    onSuccess: (snapshot) => {
      invalidateDefinitions();
      queryClient.invalidateQueries({ queryKey: queryKeys.reports.snapshots() });
      queryClient.setQueryData(queryKeys.reports.snapshot(snapshot.id), snapshot);
      toast({
        title: snapshot.status === "complete" ? "Report generated" : "Report generated with errors",
        description:
          snapshot.status === "complete"
            ? snapshot.name
            : "At least one section failed. Open the snapshot for details.",
      });
    },
    onError,
  });

  return useMemo(
    () => ({ createDefinition, updateDefinition, addSection, deleteDefinition, generateSnapshot }),
    [createDefinition, updateDefinition, addSection, deleteDefinition, generateSnapshot],
  );
}
