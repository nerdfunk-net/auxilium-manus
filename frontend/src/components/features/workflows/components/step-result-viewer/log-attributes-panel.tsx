"use client";

import { ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import type { LogAttributesPayload } from "./types";

export const LOG_ATTRIBUTES_METADATA_SUFFIX = ".log_attributes";

function isLogAttributesPayload(value: unknown): value is LogAttributesPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    ("content" in value || "snapshot" in value)
  );
}

export function extractLogAttributes(metadata: Record<string, unknown>): LogAttributesPayload[] {
  return Object.entries(metadata)
    .filter(([key]) => key.endsWith(LOG_ATTRIBUTES_METADATA_SUFFIX))
    .map(([, value]) => value)
    .filter(isLogAttributesPayload);
}

export function LogAttributesPanel({ entries }: { entries: LogAttributesPayload[] }) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {entries.map((entry, index) => (
        <div key={`log-attributes-${index}`} className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <ScrollText className="size-3.5 shrink-0 text-muted-foreground" />
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Log attributes
            </p>
            {entry.output_destination ? (
              <Badge className="text-[10px]" variant="secondary">
                {entry.output_destination === "file" ? "file" : "STDOUT"}
              </Badge>
            ) : null}
            {entry.output_format ? (
              <Badge className="text-[10px]" variant="outline">
                {entry.output_format === "pretty_text" ? "pretty text" : "JSON"}
              </Badge>
            ) : null}
            {typeof entry.device_count === "number" ? (
              <span className="text-[11px] text-muted-foreground">
                {entry.device_count} device{entry.device_count === 1 ? "" : "s"}
              </span>
            ) : null}
            {entry.written_at ? (
              <span className="text-[11px] text-muted-foreground">{entry.written_at}</span>
            ) : null}
          </div>

          {entry.file_path ? (
            <p className="mb-2 break-all text-[11px] text-muted-foreground">
              File: <span className="font-mono">{entry.file_path}</span>
              {entry.append ? " (appended)" : ""}
            </p>
          ) : null}

          {entry.content ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono">
              {entry.content}
            </pre>
          ) : (
            <p className="text-xs text-muted-foreground">No attribute dump recorded.</p>
          )}
        </div>
      ))}
    </div>
  );
}
