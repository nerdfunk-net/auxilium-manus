import { useQuery } from "@tanstack/react-query";

import type { WorkflowAiRelease } from "@/components/features/workflows/types/workflow-ai-release";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/**
 * Whether a workflow is released for Ask the Net. Its own query key, deliberately not
 * queryKeys.workflows.detail(id) (see query-keys.ts): the canvas rehydrates from that one.
 * Always refetched on mount, because saving the canvas clears a release on the server.
 */
export function useWorkflowAiReleaseQuery(workflowId: number | null, enabled: boolean) {
  const { apiCall } = useApi();

  return useQuery<WorkflowAiRelease>({
    queryKey: workflowId
      ? queryKeys.workflows.aiRelease(workflowId)
      : ["workflows", "ai-release", "disabled"],
    queryFn: () => apiCall(`workflows/${workflowId}`, { method: "GET" }),
    enabled: !!workflowId && enabled,
    staleTime: 0,
  });
}
