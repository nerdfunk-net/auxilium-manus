import { useQuery } from "@tanstack/react-query";

import type { WorkflowAiSession } from "@/components/features/workflows/types/workflow-ai-session";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const POLL_INTERVAL_MS = 5000;

/**
 * A workflow's AI-updates session status. Mirrors useWorkflowRunQuery's
 * self-referential refetchInterval: polls only while the last-known result
 * says a session is active, so enabling the toggle (which pushes fresh data
 * into this query's cache via useWorkflowAiSessionMutations) starts polling,
 * and disabling/expiry stops it — no caller-supplied flag needed, and every
 * consumer of this hook (the toolbar toggle, the reload banner) shares one
 * correctly-behaving poll. Its own query key, deliberately not
 * queryKeys.workflows.detail(id) — see query-keys.ts.
 */
export function useWorkflowAiSessionQuery(workflowId: number | null) {
  const { apiCall } = useApi();

  return useQuery<WorkflowAiSession>({
    queryKey: workflowId
      ? queryKeys.workflows.aiSession(workflowId)
      : ["workflows", "ai-session", "disabled"],
    queryFn: () => apiCall(`workflows/${workflowId}/ai-session`, { method: "GET" }),
    enabled: !!workflowId,
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowAiSession | undefined;
      return data?.active ? POLL_INTERVAL_MS : false;
    },
  });
}
