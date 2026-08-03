"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  WorkflowSchedule,
  WorkflowScheduleUpsert,
} from "@/components/features/workflows/types/workflow-schedule";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowScheduleMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const upsertSchedule = useMutation({
    mutationFn: ({ workflowId, data }: { workflowId: number; data: WorkflowScheduleUpsert }) =>
      apiCall<WorkflowSchedule>(`workflows/${workflowId}/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.workflows.schedule(updated.workflow_id), updated);
    },
  });

  const deleteSchedule = useMutation({
    mutationFn: (workflowId: number) =>
      apiCall<void>(`workflows/${workflowId}/schedule`, { method: "DELETE" }),
    onSuccess: (_data, workflowId) => {
      queryClient.setQueryData(queryKeys.workflows.schedule(workflowId), null);
    },
  });

  return { upsertSchedule, deleteSchedule };
}
