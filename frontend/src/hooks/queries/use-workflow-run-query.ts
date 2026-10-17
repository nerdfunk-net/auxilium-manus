import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { WorkflowRunDetail } from "@/components/features/workflows/types/workflow-runs";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import { progressSignature, useWorkflowRunProgressQuery } from "./use-workflow-run-progress-query";

/**
 * The full run (every step's output). It is not polled: the light progress endpoint is, and the
 * full run is fetched again only when the progress says something changed (a step moved on, the
 * run ended, a batch was approved) — not every 2 seconds for megabytes that did not change.
 */
export function useWorkflowRunQuery(runId: number | null) {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const progress = useWorkflowRunProgressQuery(runId);
  const signature = progress.data ? progressSignature(progress.data) : null;
  const lastSignature = useRef<string | null>(null);

  useEffect(() => {
    lastSignature.current = null;
  }, [runId]);

  useEffect(() => {
    if (!runId || signature === null) return;
    const previous = lastSignature.current;
    lastSignature.current = signature;
    // The first answer only establishes the baseline: the detail query is already fetching.
    if (previous !== null && previous !== signature) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
    }
  }, [runId, signature, queryClient]);

  const detail = useQuery<WorkflowRunDetail>({
    queryKey: runId ? queryKeys.workflowRuns.detail(runId) : ["workflow-runs", "disabled"],
    queryFn: () => apiCall(`runs/${runId}`, { method: "GET" }),
    enabled: !!runId,
    staleTime: 0,
  });

  // The first progress answer and the first full fetch race: if the run moved on in between,
  // the full copy is older than the progress. Fetch it again once instead of waiting for a
  // change that may never come (the run already ended).
  const progressStatus = progress.data?.status;
  const detailStatus = detail.data?.status;
  const detailFetching = detail.isFetching;
  useEffect(() => {
    if (!runId || detailFetching) return;
    if (progressStatus && detailStatus && progressStatus !== detailStatus) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflowRuns.detail(runId) });
    }
  }, [runId, progressStatus, detailStatus, detailFetching, queryClient]);

  return detail;
}
