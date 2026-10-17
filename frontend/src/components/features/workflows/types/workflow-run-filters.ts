import type { WorkflowRunStatus } from "./workflow-runs";

/** Run-level statuses plus `skipped` (runs with at least one skipped step). */
export type WorkflowRunListStatusFilter = WorkflowRunStatus | "skipped";

export interface WorkflowRunListFilters {
  statuses: WorkflowRunListStatusFilter[];
  createdFrom: string | null;
  createdTo: string | null;
}

export const EMPTY_WORKFLOW_RUN_FILTERS: WorkflowRunListFilters = {
  statuses: [],
  createdFrom: null,
  createdTo: null,
};

export function hasActiveWorkflowRunFilters(filters: WorkflowRunListFilters): boolean {
  return filters.statuses.length > 0 || !!filters.createdFrom || !!filters.createdTo;
}

export interface WorkflowRunListPage {
  limit: number;
  offset: number;
}

/** The runs endpoint answers at most this many runs per request (`le=200` on the backend). */
export const MAX_RUNS_PAGE_SIZE = 200;
export const DEFAULT_RUNS_PAGE_SIZE = 50;

export function buildWorkflowRunsListQuery(
  filters: WorkflowRunListFilters,
  page?: WorkflowRunListPage,
): string {
  const params = new URLSearchParams();
  if (page) {
    params.set("limit", String(page.limit));
    params.set("offset", String(page.offset));
  }
  for (const status of filters.statuses) {
    params.append("status", status);
  }
  if (filters.createdFrom) {
    params.set("created_from", toDayStartIso(filters.createdFrom));
  }
  if (filters.createdTo) {
    params.set("created_to", toDayEndIso(filters.createdTo));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function toDayStartIso(dateOnly: string): string {
  return new Date(`${dateOnly}T00:00:00`).toISOString();
}

function toDayEndIso(dateOnly: string): string {
  return new Date(`${dateOnly}T23:59:59.999`).toISOString();
}
