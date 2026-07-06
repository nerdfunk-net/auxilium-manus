import { useQuery } from "@tanstack/react-query";

import type { WorkflowRunDetail } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const ACTIVE_STATUSES = new Set(["pending", "running", "paused"]);

export function useWorkflowRunQuery(runId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowRunDetail>({
    queryKey: runId ? queryKeys.workflowRuns.detail(runId) : ["workflow-runs", "disabled"],
    queryFn: () => apiCall(`runs/${runId}`, { method: "GET" }),
    enabled: !!runId,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowRunDetail | undefined;
      if (!data) return 2000;
      return ACTIVE_STATUSES.has(data.status) ? 2000 : false;
    },
  });
}
