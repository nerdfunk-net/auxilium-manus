import { useQuery } from "@tanstack/react-query";

import type { WorkflowRunListFilters } from "@/components/features/workflows/types/workflow-run-filters";
import {
  buildWorkflowRunsListQuery,
  EMPTY_WORKFLOW_RUN_FILTERS,
} from "@/components/features/workflows/types/workflow-run-filters";
import type { WorkflowRunListResponse } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

const ACTIVE_STATUSES = new Set(["pending", "running"]);

function filtersCacheKey(filters: WorkflowRunListFilters): string {
  return JSON.stringify({
    statuses: [...filters.statuses].sort(),
    createdFrom: filters.createdFrom,
    createdTo: filters.createdTo,
  });
}

interface UseWorkflowRunsQueryOptions {
  filters?: WorkflowRunListFilters;
}

const DEFAULT_OPTIONS: UseWorkflowRunsQueryOptions = {};

export function useWorkflowRunsQuery(
  workflowId: number | null,
  options: UseWorkflowRunsQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const filters = options.filters ?? EMPTY_WORKFLOW_RUN_FILTERS;
  const filtersKey = filtersCacheKey(filters);

  return useQuery<WorkflowRunListResponse>({
    queryKey: workflowId
      ? queryKeys.workflowRuns.list(workflowId, filtersKey)
      : ["workflow-runs", "disabled"],
    queryFn: () =>
      apiCall(
        `workflows/${workflowId}/runs${buildWorkflowRunsListQuery(filters)}`,
        { method: "GET" },
      ),
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
