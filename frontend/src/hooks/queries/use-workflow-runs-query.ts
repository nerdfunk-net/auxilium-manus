import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { WorkflowRunListFilters } from "@/components/features/workflows/types/workflow-run-filters";
import {
  buildWorkflowRunsListQuery,
  DEFAULT_RUNS_PAGE_SIZE,
  EMPTY_WORKFLOW_RUN_FILTERS,
} from "@/components/features/workflows/types/workflow-run-filters";
import type { WorkflowRunListResponse } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const ACTIVE_STATUSES = new Set(["pending", "running", "paused"]);

function filtersCacheKey(filters: WorkflowRunListFilters, limit: number, offset: number): string {
  return JSON.stringify({
    statuses: [...filters.statuses].sort(),
    createdFrom: filters.createdFrom,
    createdTo: filters.createdTo,
    limit,
    offset,
  });
}

interface UseWorkflowRunsQueryOptions {
  filters?: WorkflowRunListFilters;
  /** Page size (newest runs first); the backend caps it at 200. */
  limit?: number;
  offset?: number;
}

const DEFAULT_OPTIONS: UseWorkflowRunsQueryOptions = {};

export function useWorkflowRunsQuery(
  workflowId: number | null,
  options: UseWorkflowRunsQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const filters = options.filters ?? EMPTY_WORKFLOW_RUN_FILTERS;
  const limit = options.limit ?? DEFAULT_RUNS_PAGE_SIZE;
  const offset = options.offset ?? 0;
  const filtersKey = filtersCacheKey(filters, limit, offset);

  return useQuery<WorkflowRunListResponse>({
    queryKey: workflowId
      ? queryKeys.workflowRuns.list(workflowId, filtersKey)
      : queryKeys.workflowRuns.all,
    queryFn: () =>
      apiCall(
        `workflows/${workflowId}/runs${buildWorkflowRunsListQuery(filters, { limit, offset })}`,
        { method: "GET" },
      ),
    enabled: !!workflowId,
    staleTime: 0,
    // Growing the page keeps the rows already on screen while the larger page loads.
    placeholderData: keepPreviousData,
    // While a run is active this refetches one page of summaries, not the whole history.
    refetchInterval: (query) => {
      const data = query.state.data as WorkflowRunListResponse | undefined;
      if (!data) return false;
      const hasActive = data.runs.some((r) => ACTIVE_STATUSES.has(r.status));
      return hasActive ? 2000 : false;
    },
  });
}
