"use client";

import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type { ChangeRequestDetail } from "../types/change-request";

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

interface ApproveVariables {
  id: number;
  deployWorkflowId?: number | null;
}

interface RejectVariables {
  id: number;
  reason?: string;
}

export function useChangeRequestMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = (id: number) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.changeRequests.detail(id) });
    queryClient.invalidateQueries({ queryKey: queryKeys.changeRequests.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.all });
  };

  const post = (path: string, body: Record<string, unknown>) =>
    apiCall<ChangeRequestDetail>(`change-requests/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  const approve = useMutation({
    mutationFn: ({ id, deployWorkflowId }: ApproveVariables) =>
      post(`${id}/approve`, { deploy_workflow_id: deployWorkflowId ?? null }),
    onSuccess: (_data, { id }) => {
      invalidate(id);
      toast({ title: "Deploying", description: "The deploy run has been queued." });
    },
    onError: (error, { id }) => {
      invalidate(id);
      toast({ title: "Failed to approve", description: getErrorMessage(error), variant: "destructive" });
    },
  });

  const deploy = useMutation({
    mutationFn: ({ id, deployWorkflowId }: ApproveVariables) =>
      post(`${id}/deploy`, { deploy_workflow_id: deployWorkflowId ?? null }),
    onSuccess: (_data, { id }) => {
      invalidate(id);
      toast({ title: "Deploying", description: "The deploy run has been queued." });
    },
    onError: (error, { id }) => {
      invalidate(id);
      toast({ title: "Failed to deploy", description: getErrorMessage(error), variant: "destructive" });
    },
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: RejectVariables) =>
      post(`${id}/reject`, { reason: reason ?? null }),
    onSuccess: (_data, { id }) => {
      invalidate(id);
      toast({ description: "Change request rejected." });
    },
    onError: (error, { id }) => {
      invalidate(id);
      toast({ title: "Failed to reject", description: getErrorMessage(error), variant: "destructive" });
    },
  });

  return useMemo(() => ({ approve, deploy, reject }), [approve, deploy, reject]);
}
