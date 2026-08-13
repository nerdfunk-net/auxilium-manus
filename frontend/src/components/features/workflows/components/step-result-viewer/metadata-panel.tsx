"use client";

import { DEBUG_LOGS_METADATA_SUFFIX } from "./debug-logs-panel";
import { LOG_ATTRIBUTES_METADATA_SUFFIX } from "./log-attributes-panel";

export function metadataWithoutDebugPanels(metadata: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(metadata).filter(
      ([key]) =>
        !key.endsWith(DEBUG_LOGS_METADATA_SUFFIX) &&
        !key.endsWith(LOG_ATTRIBUTES_METADATA_SUFFIX),
    ),
  );
}

export function MetadataPanel({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata);
  if (entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No step metadata recorded.</p>
    );
  }

  return (
    <div className="space-y-1">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="min-w-0 space-y-1 rounded border bg-background/60 px-2 py-1.5 text-xs"
        >
          <span className="block break-all font-mono text-muted-foreground">{key}</span>
          <span className="block max-h-24 overflow-auto break-all font-mono">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </span>
        </div>
      ))}
    </div>
  );
}
