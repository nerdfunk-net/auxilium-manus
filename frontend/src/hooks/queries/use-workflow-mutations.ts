"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type {
  WorkflowCreate,
  WorkflowResponse,
  WorkflowUpdate,
} from "@/components/features/workflows/types/workflow-persistence";

export function useWorkflowMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const createWorkflow = useMutation({
    mutationFn: (data: WorkflowCreate) =>
      apiCall<WorkflowResponse>("workflows", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.list() });
    },
  });

  const updateWorkflow = useMutation({
    mutationFn: ({ id, data }: { id: number; data: WorkflowUpdate }) =>
      apiCall<WorkflowResponse>(`workflows/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.list() });
      queryClient.invalidateQueries({
        queryKey: queryKeys.workflows.detail(updated.id),
      });
    },
  });

  const deleteWorkflow = useMutation({
    mutationFn: (id: number) =>
      apiCall<void>(`workflows/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.workflows.list() });
    },
  });

  return { createWorkflow, updateWorkflow, deleteWorkflow };
}
