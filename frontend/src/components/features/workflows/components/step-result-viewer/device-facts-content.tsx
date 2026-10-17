"use client";

import { Badge } from "@/components/ui/badge";

import { ContentViewer } from "./content-viewer";
import type { ParsedCommandEntry } from "./types";

/**
 * Renders the bare `{parsed, error}` entries `getFactsEntries` finds —
 * written by batfish-extract-facts, batfish-validate-facts, and the
 * `devices` outcome of batfish-node-properties/batfish-interface-properties.
 * Each entry is this device's own data only (see those steps' docs for why
 * that distinction matters — the workflow-level "Batfish result" panel
 * elsewhere in this dialog covers every queried node combined, not just
 * this one).
 */
export function DeviceFactsContent({
  entries,
  expanded = false,
}: {
  entries: Array<{ key: string; entry: ParsedCommandEntry }>;
  expanded?: boolean;
}) {
  return (
    <div className="mt-2 space-y-3">
      {entries.map(({ key, entry }) => (
        <div key={key} className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono font-medium">{key}</span>
            <Badge className="text-[10px]" variant={entry.error ? "destructive" : "secondary"}>
              {entry.error ? "error" : "ok"}
            </Badge>
            {entry.error ? <span className="text-muted-foreground">{entry.error}</span> : null}
          </div>
          {entry.parsed != null ? (
            <ContentViewer
              label="Parsed"
              content={JSON.stringify(entry.parsed, null, 2)}
              downloadName={key}
              height={expanded ? "full" : "sm"}
            />
          ) : null}
        </div>
      ))}
    </div>
  );
}
