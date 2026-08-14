import { Ban, CheckCircle2, Loader2, Pause, XCircle } from "lucide-react";

import type { WorkflowRunStatus } from "../types/workflow-runs";

export function formatDuration(started: string | null, finished: string | null): string {
  if (!started) return "—";
  const start = new Date(started).getTime();
  const end = finished ? new Date(finished).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function RunStatusIcon({ status }: { status: WorkflowRunStatus }) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="size-4 shrink-0 text-success-foreground" />;
    case "failed":
      return <XCircle className="size-4 shrink-0 text-destructive" />;
    case "cancelled":
      return <Ban className="size-4 shrink-0 text-muted-foreground" />;
    case "paused":
      return <Pause className="size-4 shrink-0 text-warning-foreground" />;
    case "running":
    case "pending":
      return <Loader2 className="size-4 shrink-0 animate-spin text-step" />;
  }
}
