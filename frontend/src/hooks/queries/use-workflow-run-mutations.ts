import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import { useToast } from "@/hooks/use-toast";
import type {
  TriggerRunRequest,
  WorkflowRunDetail,
} from "@/components/features/workflows/types/workflow-runs";

type TriggerRunVariables = TriggerRunRequest & { workflowId?: number };

export function useTriggerRunMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, TriggerRunVariables>({
    mutationFn: ({ workflowId: overrideId, ...body }) => {
      const targetId = overrideId ?? workflowId;
      if (!targetId) {
        throw new Error("Workflow must be saved before running");
      }
      return apiCall(`workflows/${targetId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    onSuccess: (_data, variables) => {
      const targetId = variables.workflowId ?? workflowId;
      if (targetId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", targetId],
        });
      }
      toast({ title: "Run queued", description: "Workflow execution has been started." });
    },
    onError: (error) => {
      toast({
        title: "Failed to start run",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useCancelRunMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, number>({
    mutationFn: (runId) =>
      apiCall(`runs/${runId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: (_data, runId) => {
      if (workflowId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", workflowId],
        });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({ title: "Run cancelled", description: "The run has been cancelled." });
    },
    onError: (error) => {
      toast({
        title: "Failed to cancel run",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useStepRunMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, number>({
    mutationFn: (runId) =>
      apiCall(`runs/${runId}/step`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: (_data, runId) => {
      if (workflowId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", workflowId],
        });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
    },
    onError: (error, runId) => {
      // A stray click can 409 if the run already advanced past this step
      // (e.g. it just finished) — refresh so the UI reflects reality instead
      // of leaving the stale "paused" snapshot on screen.
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({
        title: "Failed to advance run",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useContinueRunMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, number>({
    mutationFn: (runId) =>
      apiCall(`runs/${runId}/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: (_data, runId) => {
      if (workflowId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", workflowId],
        });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({ title: "Resuming", description: "Running the rest of the workflow without pausing." });
    },
    onError: (error, runId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({
        title: "Failed to resume run",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useApproveBatchMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, number>({
    mutationFn: (runId) =>
      apiCall(`runs/${runId}/approve-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: (_data, runId) => {
      if (workflowId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", workflowId],
        });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({ title: "Batch released", description: "Running the next device batch." });
    },
    onError: (error, runId) => {
      // A stray click can 409 if the run already advanced past this batch
      // (e.g. it was just approved from elsewhere) — refresh so the UI
      // reflects reality instead of leaving the stale "paused" snapshot.
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({
        title: "Failed to release batch",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}

export function useApproveAllMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, number>({
    mutationFn: (runId) =>
      apiCall(`runs/${runId}/approve-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: (_data, runId) => {
      if (workflowId) {
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.workflowRuns.all, "list", workflowId],
        });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({
        title: "Running all remaining batches",
        description: "No further approval pauses for this run.",
      });
    },
    onError: (error, runId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
      toast({
        title: "Failed to run remaining batches",
        description: error.message,
        variant: "destructive",
      });
    },
  });
}
