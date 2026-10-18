"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type HatchetChildSummary,
  useHatchetRunDiagnosticsQuery,
} from "@/hooks/queries/use-hatchet-diagnostics-query";
import { formatTime } from "./run-status-icon";

interface RunEnginePanelProps {
  runId: number;
}

function formatDuration(durationMs: number | null): string {
  if (durationMs == null) return "—";
  return durationMs < 1000 ? `${durationMs} ms` : `${(durationMs / 1000).toFixed(1)} s`;
}

function ChildSummaryStrip({ summary }: { summary: HatchetChildSummary }) {
  const counts: Array<[string, number, "secondary" | "destructive" | "outline"]> = [
    ["completed", summary.completed, "secondary"],
    ["failed", summary.failed, "destructive"],
    ["cancelled", summary.cancelled, "outline"],
    ["running", summary.running, "outline"],
    ["queued", summary.queued, "outline"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-medium">
        {summary.total} {summary.total === 1 ? "group" : "groups"}
      </span>
      {counts
        .filter(([, count]) => count > 0)
        .map(([label, count, variant]) => (
          <Badge key={label} variant={variant}>
            {count} {label}
          </Badge>
        ))}
      {!summary.exact ? (
        <span className="text-muted-foreground">
          approximate: the engine&apos;s totals were unavailable
        </span>
      ) : null}
    </div>
  );
}

/** What the Hatchet engine reports for a run, next to the app's own view of it (operators only). */
export function RunEnginePanel({ runId }: RunEnginePanelProps) {
  const { data, isLoading, isError, isFetching, refetch } = useHatchetRunDiagnosticsQuery(
    runId,
    true,
  );

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-6 py-3 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Asking the engine…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="px-6 py-3 text-xs text-destructive">
        Engine details could not be loaded.
      </div>
    );
  }

  return (
    <div className="space-y-3 px-6 py-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">Engine status</span>
          <Badge variant={data.engine_reachable ? "secondary" : "destructive"}>
            {data.engine_reachable ? (data.engine_status ?? "unknown") : "unreachable"}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 text-xs"
          disabled={isFetching}
          onClick={() => void refetch()}
        >
          <RefreshCw className={`size-3.5 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {!data.engine_reachable || data.engine_status == null ? (
        <p className="text-muted-foreground">{data.message}</p>
      ) : null}

      {data.mismatch ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>App and engine disagree</AlertTitle>
          <AlertDescription>{data.mismatch}</AlertDescription>
        </Alert>
      ) : null}

      {data.tasks.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Task</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Attempt</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.tasks.map((task, index) => (
              <TableRow key={`${task.name}-${index}`}>
                <TableCell className="font-mono">{task.name}</TableCell>
                <TableCell>{task.status}</TableCell>
                <TableCell>{task.attempt ?? "—"}</TableCell>
                <TableCell>{formatDuration(task.duration_ms)}</TableCell>
                <TableCell className="max-w-xs whitespace-pre-wrap break-words">
                  {task.error_message ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}

      {data.child_summary ? (
        <div className="space-y-1.5">
          <ChildSummaryStrip summary={data.child_summary} />
          {data.child_runs.length > 0 ? (
            <>
              <p className="font-medium">Failed and active groups</p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Group</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.child_runs.map((child) => (
                    <TableRow key={child.hatchet_run_id}>
                      <TableCell>
                        {child.child_index != null ? `#${child.child_index}` : child.name}
                      </TableCell>
                      <TableCell>{child.status}</TableCell>
                      <TableCell>
                        {child.started_at ? formatTime(child.started_at) : "—"}
                      </TableCell>
                      <TableCell className="max-w-xs whitespace-pre-wrap break-words">
                        {child.error_message ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          ) : (
            <p className="text-muted-foreground">No failed or active groups.</p>
          )}
          {data.child_summary.truncated ? (
            <p className="text-muted-foreground">
              {data.child_summary.exact
                ? `Showing ${data.child_summary.listed} of ${
                    data.child_summary.failed +
                    data.child_summary.cancelled +
                    data.child_summary.running +
                    data.child_summary.queued
                  } failed and active groups.`
                : `Showing ${data.child_summary.listed} failed and active groups; there may be more.`}
              {data.dashboard_url ? (
                <>
                  {" "}
                  <a
                    className="underline"
                    href={data.dashboard_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    See all in Hatchet
                  </a>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      ) : null}

      {data.events.length > 0 ? (
        <div>
          <p className="mb-1 font-medium">
            Engine events{data.events_truncated ? " (older events not shown)" : ""}
          </p>
          <ul className="max-h-48 space-y-0.5 overflow-y-auto font-mono">
            {data.events.map((event, index) => (
              <li key={`${event.timestamp}-${index}`} className="text-muted-foreground">
                {formatTime(event.timestamp)} · {event.event_type}
                {event.task_name ? ` · ${event.task_name}` : ""}
                {event.error_message ? ` · ${event.error_message}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
