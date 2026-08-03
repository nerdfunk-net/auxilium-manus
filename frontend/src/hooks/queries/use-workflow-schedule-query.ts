import { useQuery } from "@tanstack/react-query";

import type { WorkflowSchedule } from "@/components/features/workflows/types/workflow-schedule";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowScheduleQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowSchedule | null>({
    queryKey: workflowId ? queryKeys.workflows.schedule(workflowId) : ["workflows", "schedule", "disabled"],
    queryFn: () => apiCall(`workflows/${workflowId}/schedule`, { method: "GET" }),
    enabled: !!workflowId,
  });
}
