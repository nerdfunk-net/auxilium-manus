"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { WorkflowRunResult } from "../types/ai-assistant";

interface WorkflowRunConfirmResponse {
  run_id: number;
  workflow_id: number;
}

/**
 * The user's click on a proposed workflow run. The body is only the signed token: workflow, inputs
 * and devices are in it, so the request cannot start more than the card showed. Not retried: a
 * retry would start a second run.
 */
export function useWorkflowRunConfirmMutation() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async (token: string): Promise<WorkflowRunResult> => {
      const response = await apiCall<WorkflowRunConfirmResponse>(
        "ai/exec/workflow-run",
        { method: "POST", body: JSON.stringify({ token }) },
      );
      return { runId: response.run_id, workflowId: response.workflow_id };
    },
  });
}
