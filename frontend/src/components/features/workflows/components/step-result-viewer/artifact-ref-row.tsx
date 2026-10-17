"use client";

import type { ArtifactRef } from "@/lib/workflow-context-types";

export function ArtifactRefRow({ label, artifactRef }: { label: string; artifactRef: ArtifactRef }) {
  return (
    <div className="rounded border bg-background/60 px-2 py-1.5 text-xs">
      <p className="font-medium text-muted-foreground">{label}</p>
      <p className="text-muted-foreground">
        {artifactRef.kind}
        {artifactRef.size_bytes != null ? ` · ${artifactRef.size_bytes} bytes` : ""}
      </p>
    </div>
  );
}
