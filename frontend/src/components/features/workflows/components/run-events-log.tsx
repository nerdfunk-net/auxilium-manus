"use client";

import { AlertCircle, AlertTriangle, Info } from "lucide-react";

import { formatTime } from "./run-status-icon";
import type { WorkflowRunEvent } from "../types/workflow-runs";

const LEVEL_ICON = {
  info: { Icon: Info, className: "text-muted-foreground" },
  warning: { Icon: AlertTriangle, className: "text-warning-foreground" },
  error: { Icon: AlertCircle, className: "text-destructive" },
} as const;

function levelIcon(level: string) {
  return level === "error" || level === "warning" ? LEVEL_ICON[level] : LEVEL_ICON.info;
}

/** Chronological list of live events (connect attempts, retries, failures) for one step. */
export function RunEventsLog({ events }: { events: readonly WorkflowRunEvent[] }) {
  if (events.length === 0) {
    return null;
  }
  return (
    <div className="space-y-1" aria-label="Live events">
      <p className="text-xs font-semibold">Live events</p>
      <ul className="max-h-48 space-y-0.5 overflow-y-auto rounded border bg-muted/30 p-2 font-mono text-[11px]">
        {events.map((event) => {
          const { Icon, className } = levelIcon(event.level);
          return (
            <li key={event.id} className="flex items-start gap-1.5">
              <Icon className={`mt-0.5 size-3 shrink-0 ${className}`} aria-hidden />
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {formatTime(event.created_at)}
              </span>
              {event.child_index !== null ? (
                <span className="shrink-0 text-muted-foreground">#{event.child_index + 1}</span>
              ) : null}
              <span className="min-w-0 break-words">
                {event.device_name ? `${event.device_name}: ` : ""}
                {event.message}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
