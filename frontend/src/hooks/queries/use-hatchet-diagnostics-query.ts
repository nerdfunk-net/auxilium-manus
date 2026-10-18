"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface HatchetTaskInfo {
  name: string;
  status: string;
  attempt: number | null;
  retry_count: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

export interface HatchetTaskEventInfo {
  task_name: string | null;
  event_type: string;
  timestamp: string;
  message: string;
  error_message: string | null;
  attempt: number | null;
}

export interface HatchetChildRun {
  hatchet_run_id: string;
  name: string;
  status: string;
  child_index: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface HatchetChildSummary {
  total: number;
  completed: number;
  failed: number;
  cancelled: number;
  running: number;
  queued: number;
  /** False when the engine's counts were unavailable and only the listed rows were counted. */
  exact: boolean;
  listed: number;
  truncated: boolean;
}

export interface HatchetRunDiagnostics {
  engine_reachable: boolean;
  message: string;
  hatchet_run_id: string | null;
  engine_status: string | null;
  mismatch: string | null;
  dashboard_url: string | null;
  tasks: HatchetTaskInfo[];
  events: HatchetTaskEventInfo[];
  /** Failed/cancelled groups first, then running, then queued; completed groups are only counted. */
  child_runs: HatchetChildRun[];
  child_summary: HatchetChildSummary | null;
  events_truncated: boolean;
}

export interface HatchetWorkerInfo {
  /** Engine id; several rows can share a name. */
  id: string;
  name: string;
  status: string | null;
  type: string | null;
  last_heartbeat_at: string | null;
  slots_used: number | null;
  slots_total: number | null;
  registered_workflows: string[];
}

export interface HatchetWorkersData {
  engine_reachable: boolean;
  message: string;
  workers: HatchetWorkerInfo[];
  missing_workers: string[];
}

/** The engine's view of one run. Loaded on demand (``enabled``) and refetched by hand. */
export function useHatchetRunDiagnosticsQuery(runId: number | null, enabled: boolean) {
  const { apiCall } = useApi();

  return useQuery<HatchetRunDiagnostics>({
    queryKey: queryKeys.hatchet.runDiagnostics(runId ?? 0),
    queryFn: () => apiCall(`hatchet/runs/${runId}`, { method: "GET" }),
    enabled: enabled && runId != null,
    staleTime: 0,
  });
}

export function useHatchetWorkersQuery() {
  const { apiCall } = useApi();

  return useQuery<HatchetWorkersData>({
    queryKey: queryKeys.hatchet.workers(),
    queryFn: () => apiCall("hatchet/workers", { method: "GET" }),
    staleTime: 10 * 1000,
  });
}
