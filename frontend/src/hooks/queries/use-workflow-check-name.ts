"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export interface WorkflowNameCheckInput {
  name: string;
  folder: string;
  visibility: string;
  excludeId?: number;
}

export interface WorkflowNameCheckResponse {
  available: boolean;
  message?: string;
  existing_id?: number;
}

export function useWorkflowCheckNameMutation() {
  const { apiCall } = useApi();
  return useMutation({
    mutationFn: (input: WorkflowNameCheckInput) => {
      const params = new URLSearchParams({
        name: input.name,
        folder: input.folder,
        visibility: input.visibility,
      });
      if (input.excludeId !== undefined) {
        params.set("exclude_id", String(input.excludeId));
      }
      return apiCall<WorkflowNameCheckResponse>(
        `workflows/check-name?${params.toString()}`,
      );
    },
  });
}
