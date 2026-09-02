"use client";

import { Loader2 } from "lucide-react";

import { useArtifactQuery } from "@/hooks/queries/use-artifact-query";
import type { ArtifactRef } from "@/lib/workflow-context-types";

import { ContentViewer } from "./content-viewer";

export function ConfigArtifactPanel({
  runId,
  label,
  artifactRef,
  expanded = false,
}: {
  runId: number;
  label: string;
  artifactRef: ArtifactRef;
  /** Render at full detail-dialog height instead of the inline preview height. */
  expanded?: boolean;
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
    <ContentViewer
      content={data.content}
      label={label}
      sizeBytes={data.size_bytes}
      downloadName={`${label.toLowerCase().replace(/\s+/g, "-")}-${data.artifact_id}`}
      height={expanded ? "full" : "sm"}
    />
  );
}
