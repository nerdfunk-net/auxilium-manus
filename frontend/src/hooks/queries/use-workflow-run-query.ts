import { useQuery } from "@tanstack/react-query";

import type { WorkflowRunDetail } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const ACTIVE_STATUSES = new Set(["pending", "running", "paused"]);
// "paused" only happens in Debug mode, where a human is actively watching and
// clicking Next Step — poll fast so the UI reflects a step's completion
// (which the backend itself reports almost instantly) without a multi-second
// lag. "pending"/"running" cover unattended/background runs, where 2s is fine.
const PAUSED_POLL_INTERVAL_MS = 500;
const ACTIVE_POLL_INTERVAL_MS = 2000;

export function useWorkflowRunQuery(runId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowRunDetail>({
    queryKey: runId ? queryKeys.workflowRuns.detail(runId) : ["workflow-runs", "disabled"],
    queryFn: () => apiCall(`runs/${runId}`, { method: "GET" }),
    enabled: !!runId,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowRunDetail | undefined;
      if (!data) return ACTIVE_POLL_INTERVAL_MS;
      if (data.status === "paused") return PAUSED_POLL_INTERVAL_MS;
      return ACTIVE_STATUSES.has(data.status) ? ACTIVE_POLL_INTERVAL_MS : false;
    },
  });
}
