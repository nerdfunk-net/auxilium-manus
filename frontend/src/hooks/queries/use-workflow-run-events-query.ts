import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import type { WorkflowRunEventPage } from "@/components/features/workflows/types/workflow-runs";
import {
  EMPTY_RUN_EVENTS,
  mergeRunEvents,
  type RunEventsState,
} from "@/components/features/workflows/utils/run-events";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const POLL_INTERVAL_MS = 2000;
const PAGE_SIZE = 500;
// A run emits at most a few thousand events (backend cap); this bounds the
// drain loop if the server ever keeps returning full pages.
const MAX_PAGES_PER_POLL = 20;

/**
 * Live run events, polled incrementally with the server's ``after_id`` cursor
 * and accumulated in the query cache. ``active`` is whether the run is still
 * pending/running/paused; once it flips to false we fetch one last time so
 * events emitted just before the run finished are not lost.
 */
export function useWorkflowRunEventsQuery(runId: number | null, active: boolean) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();

  const query = useQuery<RunEventsState>({
    queryKey: runId ? queryKeys.workflowRuns.events(runId) : ["workflow-runs", "events", "disabled"],
    queryFn: async () => {
      const key = queryKeys.workflowRuns.events(runId as number);
      const previous = queryClient.getQueryData<RunEventsState>(key);
      let state = previous;
      let cursor = previous?.nextAfterId ?? 0;
      for (let page = 0; page < MAX_PAGES_PER_POLL; page += 1) {
        const response = await apiCall<WorkflowRunEventPage>(
          `runs/${runId}/events?after_id=${cursor}&limit=${PAGE_SIZE}`,
          { method: "GET" },
        );
        state = mergeRunEvents(state, response);
        cursor = response.next_after_id;
        if (response.events.length < PAGE_SIZE) break;
      }
      return state ?? EMPTY_RUN_EVENTS;
    },
    enabled: !!runId,
    staleTime: 0,
    refetchInterval: active ? POLL_INTERVAL_MS : false,
  });

  useEffect(() => {
    if (runId && !active) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.events(runId) });
    }
  }, [runId, active, queryClient]);

  return query;
}
