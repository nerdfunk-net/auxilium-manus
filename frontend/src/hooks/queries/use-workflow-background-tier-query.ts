import { useQuery } from "@tanstack/react-query";

import type { WorkflowBackgroundTier } from "@/components/features/workflows/types/workflow-background-tier";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useWorkflowBackgroundTierQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowBackgroundTier | null>({
    queryKey: workflowId
      ? queryKeys.workflows.backgroundTier(workflowId)
      : ["workflows", "background-tier", "disabled"],
    queryFn: () => apiCall(`workflows/${workflowId}/background-tier`, { method: "GET" }),
    enabled: !!workflowId,
  });
}
