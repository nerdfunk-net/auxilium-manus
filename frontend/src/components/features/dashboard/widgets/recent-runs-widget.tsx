"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { RunStatusIcon, formatTime } from "@/components/features/workflows/components/run-status-icon";
import type { WorkflowRunStatus } from "@/components/features/workflows/types/workflow-runs";
import { useDashboardRecentRunsQuery } from "@/hooks/queries/use-dashboard-recent-runs-query";

const KNOWN_STATUSES: readonly WorkflowRunStatus[] = [
  "pending",
  "running",
  "paused",
  "success",
  "failed",
  "cancelled",
];

function toRunStatus(status: string): WorkflowRunStatus {
  return (KNOWN_STATUSES as readonly string[]).includes(status)
    ? (status as WorkflowRunStatus)
    : "pending";
}

export function RecentRunsWidget() {
  const { data, isLoading, error } = useDashboardRecentRunsQuery();

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-destructive">
        Failed to load recent runs: {error.message}
      </p>
    );
  }

  const runs = data?.runs ?? [];

  if (runs.length === 0) {
    return <p className="text-sm text-muted-foreground">No runs yet.</p>;
  }

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      {runs.map((run) => (
        <div
          className="flex items-center justify-between gap-3 rounded-md border border-border/60 px-3 py-2 text-sm"
          key={run.run_id}
        >
          <div className="flex min-w-0 items-center gap-2">
            <RunStatusIcon status={toRunStatus(run.status)} />
            <div className="min-w-0">
              <p className="truncate font-medium">{run.workflow_name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {run.triggered_by_username ?? "—"} · {formatTime(run.created_at)}
              </p>
            </div>
          </div>
          <Badge variant="outline">{run.trigger_type}</Badge>
        </div>
      ))}
      <Link
        className="text-xs font-medium text-primary hover:underline"
        href="/workflows/runs"
      >
        View all runs
      </Link>
    </div>
  );
}
