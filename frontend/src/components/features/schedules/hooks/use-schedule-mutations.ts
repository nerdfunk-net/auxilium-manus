"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type {
  ScheduleRunNowResult,
  WorkflowSchedule,
  WorkflowScheduleCreate,
  WorkflowScheduleUpdate,
} from "../types/schedule";

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

export function useScheduleMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.schedules.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.schedules() });
  };

  const createSchedule = useMutation({
    mutationFn: (data: WorkflowScheduleCreate) =>
      apiCall<WorkflowSchedule>("schedules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ description: "Schedule created." });
    },
    onError: (error: unknown) =>
      toast({ description: getErrorMessage(error), variant: "destructive" }),
  });

  const updateSchedule = useMutation({
    mutationFn: ({ id, data }: { id: number; data: WorkflowScheduleUpdate }) =>
      apiCall<WorkflowSchedule>(`schedules/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      invalidate();
      toast({ description: "Schedule saved." });
    },
    onError: (error: unknown) =>
      toast({ description: getErrorMessage(error), variant: "destructive" }),
  });

  const deleteSchedule = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ description: "Schedule removed." });
    },
    onError: (error: unknown) =>
      toast({ description: getErrorMessage(error), variant: "destructive" }),
  });

  // Starts one run now with the schedule's stored inputs; the schedule itself is untouched.
  const runNow = useMutation({
    mutationFn: ({ id }: { id: number; workflowId: number }) =>
      apiCall<ScheduleRunNowResult>(`schedules/${id}/run`, { method: "POST" }),
    onSuccess: (result, { workflowId }) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.workflowRuns.listPrefix(workflowId),
      });
      if (result.status === "failed") {
        // The run exists (and is listed as failed) but never started.
        toast({
          title: "Run could not start",
          description: result.error_message ?? "The run failed before it started.",
          variant: "destructive",
        });
        return;
      }
      toast({ title: "Run queued", description: `Run #${result.run_id} started.` });
    },
    onError: (error: unknown) =>
      toast({
        title: "Failed to start run",
        description: getErrorMessage(error),
        variant: "destructive",
      }),
  });

  return useMemo(
    () => ({ createSchedule, updateSchedule, deleteSchedule, runNow }),
    [createSchedule, updateSchedule, deleteSchedule, runNow],
  );
}
