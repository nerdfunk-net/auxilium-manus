import { useQuery } from "@tanstack/react-query";

import type { WorkflowRunProgress } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export const ACTIVE_RUN_STATUSES: ReadonlySet<string> = new Set(["pending", "running", "paused"]);
// "paused" happens during a Wait & Run batch-approval gate, where a human is actively watching and
// about to click "Run next batch" — poll fast so the UI reflects the release almost instantly.
// "pending"/"running" cover unattended/background runs, where 2s is fine.
export const PAUSED_POLL_INTERVAL_MS = 500;
export const ACTIVE_POLL_INTERVAL_MS = 2000;

/** How often to poll given the last progress answer (`false` = stop: the run is over). */
export function progressRefetchInterval(data: WorkflowRunProgress | undefined): number | false {
  if (!data) return ACTIVE_POLL_INTERVAL_MS;
  if (data.status === "paused") return PAUSED_POLL_INTERVAL_MS;
  return ACTIVE_RUN_STATUSES.has(data.status) ? ACTIVE_POLL_INTERVAL_MS : false;
}

/** A string that changes whenever anything a viewer could see changed. */
export function progressSignature(data: WorkflowRunProgress): string {
  return JSON.stringify([
    data.status,
    data.current_node_id,
    data.approval_state,
    data.finished_at,
    data.steps.map((step) => [step.step_node_id, step.status, step.finished_at]),
    data.device_groups.map((group) => [group.child_index, group.status, group.node_states]),
  ]);
}

/**
 * Polls the light progress endpoint (statuses and timestamps, no step output) until the run is
 * over. `useWorkflowRunQuery` fetches the full run only when this reports a change.
 */
export function useWorkflowRunProgressQuery(runId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowRunProgress>({
    queryKey: runId ? queryKeys.workflowRuns.progress(runId) : ["workflow-runs", "progress-disabled"],
    queryFn: () => apiCall(`runs/${runId}/progress`, { method: "GET" }),
    enabled: !!runId,
    staleTime: 0,
    refetchInterval: (query) =>
      progressRefetchInterval(query.state.data as WorkflowRunProgress | undefined),
  });
}
