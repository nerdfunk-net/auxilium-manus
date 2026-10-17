"use client";

import { Badge } from "@/components/ui/badge";

import { ConfigArtifactPanel } from "./config-artifact-panel";
import type {
  ComparisonDiffStats,
  ParsedComparisonDiffEntry,
  ParsedComparisonResultEntry,
} from "./types";

/** compare-data reports +/- line counts; compare-pyats-snapshot reports a
 * structure-aware line_count. Render whichever is present. */
function formatDiffStats(stats: ComparisonDiffStats | undefined): string | null {
  if (!stats) {
    return null;
  }
  if (stats.additions != null || stats.deletions != null) {
    return `+${stats.additions ?? 0} / -${stats.deletions ?? 0}`;
  }
  if (stats.line_count != null) {
    return `${stats.line_count} changed line${stats.line_count === 1 ? "" : "s"}`;
  }
  return null;
}

export function DeviceComparisonDiffsContent({
  runId,
  comparisonResults,
  comparisonDiffs,
  expanded = false,
}: {
  runId: number | null;
  comparisonResults: Array<{ key: string; entry: ParsedComparisonResultEntry }>;
  comparisonDiffs: Array<{ key: string; entry: ParsedComparisonDiffEntry }>;
  expanded?: boolean;
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
            {formatDiffStats(entry.diff_stats) ? (
              <span className="text-[11px] text-muted-foreground">
                {formatDiffStats(entry.diff_stats)}
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
            {formatDiffStats(entry.diff_stats) ? (
              <span className="text-[11px] text-muted-foreground">
                {formatDiffStats(entry.diff_stats)}
              </span>
            ) : null}
          </div>
          {runId == null ? (
            <p className="text-xs text-muted-foreground">
              Diff content is available from a workflow run detail view.
            </p>
          ) : (
            <>
              <ConfigArtifactPanel
                runId={runId}
                label="Unified diff"
                artifactRef={entry.artifact_ref}
                expanded={expanded}
              />
              {entry.live_snapshot_ref && entry.reference_snapshot_ref ? (
                <div className="grid gap-3 pt-1 lg:grid-cols-2">
                  <ConfigArtifactPanel
                    runId={runId}
                    label="Current snapshot"
                    artifactRef={entry.live_snapshot_ref}
                    expanded={expanded}
                  />
                  <ConfigArtifactPanel
                    runId={runId}
                    label="Baseline snapshot"
                    artifactRef={entry.reference_snapshot_ref}
                    expanded={expanded}
                  />
                </div>
              ) : null}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
