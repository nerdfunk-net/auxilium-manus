import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import { useToast } from "@/hooks/use-toast";
import type {
  TriggerRunRequest,
  WorkflowRunDetail,
} from "@/components/features/workflows/types/workflow-runs";

export function useTriggerRunMutation(workflowId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  return useMutation<WorkflowRunDetail, Error, TriggerRunRequest>({
    mutationFn: (body) =>
      apiCall(`workflows/${workflowId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      if (workflowId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.list(workflowId) });
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
        queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.list(workflowId) });
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
