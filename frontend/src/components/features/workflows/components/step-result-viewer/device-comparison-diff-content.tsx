"use client";

import { Badge } from "@/components/ui/badge";

import { ConfigArtifactPanel } from "./config-artifact-panel";
import type { ParsedComparisonDiffEntry, ParsedComparisonResultEntry } from "./types";

export function DeviceComparisonDiffsContent({
  runId,
  comparisonResults,
  comparisonDiffs,
}: {
  runId: number | null;
  comparisonResults: Array<{ key: string; entry: ParsedComparisonResultEntry }>;
  comparisonDiffs: Array<{ key: string; entry: ParsedComparisonDiffEntry }>;
}) {
  if (comparisonResults.length === 0 && comparisonDiffs.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 space-y-3">
      {comparisonResults.map(({ key, entry }) => (
        <div key={key} className="space-y-1 rounded border bg-background/60 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Comparison
            </p>
            <Badge
              className="text-[10px]"
              variant={entry.matched ? "secondary" : "destructive"}
            >
              {entry.matched ? "match" : "mismatch"}
            </Badge>
            {entry.diff_stats ? (
              <span className="text-[11px] text-muted-foreground">
                +{entry.diff_stats.additions} / -{entry.diff_stats.deletions}
              </span>
            ) : null}
          </div>
          <p className="font-mono text-[10px] text-muted-foreground">key: {key}</p>
          {entry.reference_path ? (
            <p className="break-all text-[11px] text-muted-foreground">
              reference: <span className="font-mono">{entry.reference_path}</span>
            </p>
          ) : null}
          {entry.matched ? (
            <p className="text-xs text-muted-foreground">
              Source content matches the reference file.
            </p>
          ) : entry.comparison_diff_key ? (
            <p className="text-xs text-muted-foreground">
              Diff stored at{" "}
              <span className="font-mono">{entry.comparison_diff_key}</span>
            </p>
          ) : null}
        </div>
      ))}

      {comparisonDiffs.map(({ key, entry }) => (
        <div key={key} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-[10px] text-muted-foreground">key: {key}</p>
            {entry.diff_stats ? (
              <span className="text-[11px] text-muted-foreground">
                +{entry.diff_stats.additions} / -{entry.diff_stats.deletions}
              </span>
            ) : null}
          </div>
          {runId == null ? (
            <p className="text-xs text-muted-foreground">
              Diff content is available from a workflow run detail view.
            </p>
          ) : (
            <ConfigArtifactPanel
              runId={runId}
              label="Unified diff"
              artifactRef={entry.artifact_ref}
            />
          )}
        </div>
      ))}
    </div>
  );
}
