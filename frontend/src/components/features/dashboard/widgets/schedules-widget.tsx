"use client";

import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useDashboardSchedulesQuery } from "@/hooks/queries/use-dashboard-schedules-query";

const MAX_VISIBLE_SCHEDULES = 10;

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function SchedulesWidget() {
  const { data, isLoading, error } = useDashboardSchedulesQuery();

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
        Failed to load schedules: {error.message}
      </p>
    );
  }

  const schedules = data?.schedules ?? [];

  if (schedules.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No active schedules.</p>
    );
  }

  const visible = schedules.slice(0, MAX_VISIBLE_SCHEDULES);

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      {visible.map((schedule) => (
        <div
          className="flex items-start justify-between gap-3 rounded-md border border-border/60 px-3 py-2 text-sm"
          key={schedule.schedule_id}
        >
          <div className="min-w-0">
            <p className="truncate font-medium">{schedule.workflow_name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {schedule.schedule_type === "cron"
                ? schedule.cron_expression
                : `Runs at ${formatDateTime(schedule.run_at)}`}
            </p>
            <p className="text-xs text-muted-foreground">
              Next: {formatDateTime(schedule.next_run_at)}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Badge variant="secondary">
              {schedule.schedule_type === "cron" ? "Recurring" : "Once"}
            </Badge>
            <Badge variant="outline">
              {schedule.workflow_visibility === "public" ? "Public" : "Private"}
            </Badge>
          </div>
        </div>
      ))}
      {schedules.length > MAX_VISIBLE_SCHEDULES ? (
        <p className="text-xs text-muted-foreground">
          +{schedules.length - MAX_VISIBLE_SCHEDULES} more
        </p>
      ) : null}
    </div>
  );
}
