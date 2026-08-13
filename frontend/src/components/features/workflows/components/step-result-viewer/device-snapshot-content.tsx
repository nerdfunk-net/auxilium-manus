"use client";

import { Badge } from "@/components/ui/badge";

import { ConfigArtifactPanel } from "./config-artifact-panel";
import type { SnapshotEntry } from "./types";

export function DeviceSnapshotContent({
  runId,
  entries,
}: {
  runId: number | null;
  entries: Array<{ key: string; entry: SnapshotEntry }>;
}) {
  return (
    <div className="mt-2 space-y-3">
      {entries.map(({ key, entry }) => (
        <div key={key} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">output_key: {key}</p>
          <div className="flex flex-wrap gap-1">
            {Object.entries(entry.features).map(([feature, result]) => (
              <Badge
                key={feature}
                className="text-[10px]"
                variant={result.success ? "secondary" : "destructive"}
                title={result.success ? undefined : (result.error ?? undefined)}
              >
                {feature}
              </Badge>
            ))}
          </div>
          {runId == null ? (
            <p className="text-xs text-muted-foreground">
              Snapshot content is available from a workflow run detail view.
            </p>
          ) : (
            <ConfigArtifactPanel runId={runId} label="Genie snapshot" artifactRef={entry.artifact_ref} />
          )}
        </div>
      ))}
    </div>
  );
}
