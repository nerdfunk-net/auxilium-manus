"use client";

import { Badge } from "@/components/ui/badge";
import type { CommandResult } from "@/lib/workflow-context-types";

import { ConfigArtifactPanel } from "./config-artifact-panel";

export function DeviceCommandResultsContent({
  runId,
  commandResults,
}: {
  runId: number | null;
  commandResults: Record<string, CommandResult[]>;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Command output is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {Object.entries(commandResults).map(([stepNodeId, results]) => (
        <div key={stepNodeId} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">node: {stepNodeId}</p>
          {results.map((result) => (
            <div key={`${stepNodeId}-${result.command}-${result.executed_at}`} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono font-medium">{result.command}</span>
                <Badge
                  className="text-[10px]"
                  variant={result.success ? "secondary" : "destructive"}
                >
                  {result.success ? "success" : "failed"}
                </Badge>
                {result.summary ? (
                  <span className="text-muted-foreground">{result.summary}</span>
                ) : null}
              </div>
              {result.output_ref ? (
                <ConfigArtifactPanel
                  runId={runId}
                  label="Output"
                  artifactRef={result.output_ref}
                />
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
