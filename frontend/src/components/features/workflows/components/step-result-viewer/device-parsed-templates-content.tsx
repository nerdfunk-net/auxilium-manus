"use client";

import { ConfigArtifactPanel } from "./config-artifact-panel";
import type { ParsedTemplateEntry } from "./types";

export function DeviceParsedTemplatesContent({
  runId,
  parsedEntries,
}: {
  runId: number | null;
  parsedEntries: Array<{ key: string; entry: ParsedTemplateEntry }>;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Rendered template content is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {parsedEntries.map(({ key, entry }) => (
        <div key={key} className="space-y-1">
          <p className="font-mono text-[10px] text-muted-foreground">
            node: {entry.step_node_id}
          </p>
          <ConfigArtifactPanel
            runId={runId}
            label={`Rendered template (${entry.output_key})`}
            artifactRef={entry.artifact_ref}
          />
        </div>
      ))}
    </div>
  );
}
