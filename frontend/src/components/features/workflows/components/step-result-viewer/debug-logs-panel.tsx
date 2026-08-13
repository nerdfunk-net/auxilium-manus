"use client";

import { ScrollText } from "lucide-react";

import { formatLogValue } from "./format-log-value";
import type { DebugLogsPayload } from "./types";

export const DEBUG_LOGS_METADATA_SUFFIX = ".debug_logs";

function isDebugLogsPayload(value: unknown): value is DebugLogsPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "devices" in value &&
    typeof (value as DebugLogsPayload).devices === "object"
  );
}

export function extractDebugLogs(metadata: Record<string, unknown>): DebugLogsPayload[] {
  return Object.entries(metadata)
    .filter(([key]) => key.endsWith(DEBUG_LOGS_METADATA_SUFFIX))
    .map(([, value]) => value)
    .filter(isDebugLogsPayload);
}

export function DebugLogsPanel({ logs }: { logs: DebugLogsPayload[] }) {
  if (logs.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {logs.map((entry, index) => {
        const deviceEntries = Object.values(entry.devices ?? {});
        return (
          <div key={`debug-log-${index}`} className="rounded-lg border bg-card p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <ScrollText className="size-3.5 shrink-0 text-muted-foreground" />
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Debug log
              </p>
              {entry.logged_at ? (
                <span className="text-[11px] text-muted-foreground">{entry.logged_at}</span>
              ) : null}
            </div>

            {entry.message ? (
              <p className="mb-2 text-[11px] text-muted-foreground">
                Template: <span className="font-mono">{entry.message}</span>
              </p>
            ) : null}

            {deviceEntries.length === 0 ? (
              <p className="text-xs text-muted-foreground">No devices were present in context.</p>
            ) : (
              <div className="space-y-2">
                {deviceEntries.map((deviceEntry) => (
                  <div
                    key={deviceEntry.device_id}
                    className="rounded border bg-background/60 p-2 text-xs"
                  >
                    <p className="font-medium">{deviceEntry.device_name}</p>
                    <p className="break-all font-mono text-[11px] text-muted-foreground">
                      {deviceEntry.device_id}
                    </p>
                    <pre className="mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-1.5 font-mono text-[11px]">
                      {formatLogValue(deviceEntry.message)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
