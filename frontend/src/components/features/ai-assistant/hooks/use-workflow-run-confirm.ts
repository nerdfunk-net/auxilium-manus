"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { WorkflowRunResult } from "../types/ai-assistant";

interface WorkflowRunConfirmResponse {
  run_id: number;
  workflow_id: number;
}

export interface WorkflowRunConfirmRequest {
  token: string;
  /** Credential input name -> the name of the user's own credential. */
  credentials: Record<string, string>;
  /** The user's device type for addresses outside the inventory. */
  freeIpDriver?: string;
}

/**
 * The user's click on a proposed workflow run. The workflow, inputs and devices are in the signed
 * token, so the request cannot start more than the card showed; the body adds only what the user
 * chose on the card (a credential per credential input, a device type for outside addresses). Not
 * retried: a retry would start a second run.
 */
export function useWorkflowRunConfirmMutation() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async ({
      token,
      credentials,
      freeIpDriver,
    }: WorkflowRunConfirmRequest): Promise<WorkflowRunResult> => {
      const response = await apiCall<WorkflowRunConfirmResponse>(
        "ai/exec/workflow-run",
        {
          method: "POST",
          body: JSON.stringify({
            token,
            credentials,
            ...(freeIpDriver ? { free_ip_driver: freeIpDriver } : {}),
          }),
        },
      );
      return { runId: response.run_id, workflowId: response.workflow_id };
    },
  });
}
