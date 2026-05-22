import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import type { WorkflowRunListResponse } from "@/components/features/workflows/types/workflow-runs";

const ACTIVE_STATUSES = new Set(["pending", "running"]);

export function useWorkflowRunsQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowRunListResponse>({
    queryKey: workflowId ? queryKeys.workflowRuns.list(workflowId) : ["workflow-runs", "disabled"],
    queryFn: () => apiCall(`workflows/${workflowId}/runs`, { method: "GET" }),
    enabled: !!workflowId,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowRunListResponse | undefined;
      if (!data) return false;
      const hasActive = data.runs.some((r) => ACTIVE_STATUSES.has(r.status));
      return hasActive ? 2000 : false;
    },
  });
}
