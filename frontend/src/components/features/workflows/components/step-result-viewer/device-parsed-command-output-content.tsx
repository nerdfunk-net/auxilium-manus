"use client";

import { Badge } from "@/components/ui/badge";

import { ContentViewer } from "./content-viewer";
import type { ParsedCommandOutputEntry } from "./types";

export function DeviceParsedCommandOutputContent({
  entries,
  expanded = false,
}: {
  entries: Array<{ key: string; entry: ParsedCommandOutputEntry }>;
  expanded?: boolean;
}) {
  return (
    <div className="mt-2 space-y-3">
      {entries.map(({ key, entry }) => (
        <div key={key} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">parsed.{key}</p>
          {Object.entries(entry).map(([command, result]) => (
            <div key={`${key}-${command}`} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono font-medium">{command}</span>
                <Badge
                  className="text-[10px]"
                  variant={result.error ? "destructive" : "secondary"}
                >
                  {result.error ? "not parsed" : "parsed"}
                </Badge>
                {result.error ? (
                  <span className="text-muted-foreground">{result.error}</span>
                ) : null}
              </div>
              {result.parsed != null ? (
                <ContentViewer
                  label="Parsed"
                  content={JSON.stringify(result.parsed, null, 2)}
                  downloadName={`${key}-${command}`}
                  height={expanded ? "full" : "sm"}
                />
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
