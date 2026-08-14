"use client";

import { Loader2 } from "lucide-react";

import { useArtifactQuery } from "@/hooks/queries/use-artifact-query";
import type { ArtifactRef } from "@/lib/workflow-context-types";

export function ConfigArtifactPanel({
  runId,
  label,
  artifactRef,
}: {
  runId: number;
  label: string;
  artifactRef: ArtifactRef;
}) {
  const { data, isLoading, error } = useArtifactQuery({ runId, artifactRef });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Loading {label.toLowerCase()}…
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="text-xs text-warning-foreground">
        {label} unavailable — re-run the workflow to persist config content.
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <pre className="max-h-60 overflow-auto break-all rounded bg-muted/40 p-2 text-[11px] font-mono whitespace-pre-wrap">
        {data.content}
      </pre>
    </div>
  );
}
