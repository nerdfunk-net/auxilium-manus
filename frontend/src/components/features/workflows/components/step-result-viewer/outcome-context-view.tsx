"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";
import type { WorkflowContext } from "@/lib/workflow-context-types";

import { DebugLogsPanel, extractDebugLogs } from "./debug-logs-panel";
import { DevicesSection } from "./devices-section";
import { LogAttributesPanel, extractLogAttributes } from "./log-attributes-panel";
import { MetadataPanel, metadataWithoutDebugPanels } from "./metadata-panel";

export function OutcomeContextView({
  context,
  runId,
  compact = false,
}: {
  context: WorkflowContext;
  runId?: number | null;
  compact?: boolean;
}) {
  const devices = Object.values(context.devices);
  const pendingCommandNodes = Object.keys(context.pending_commands);
  const debugLogs = useMemo(() => extractDebugLogs(context.metadata), [context.metadata]);
  const logAttributes = useMemo(
    () => extractLogAttributes(context.metadata),
    [context.metadata],
  );
  const remainingMetadata = useMemo(
    () => metadataWithoutDebugPanels(context.metadata),
    [context.metadata],
  );

  return (
    <div className={cn("min-w-0 overflow-hidden", compact ? "space-y-2" : "space-y-4")}>
      <DevicesSection devices={devices} runId={runId} compact={compact} />

      {debugLogs.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Debug logs
          </p>
          <DebugLogsPanel logs={debugLogs} />
        </div>
      ) : null}

      {logAttributes.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Log attributes
          </p>
          <LogAttributesPanel entries={logAttributes} />
        </div>
      ) : null}

      {!compact ? (
        <>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Metadata
            </p>
            <MetadataPanel metadata={remainingMetadata} />
          </div>

          {pendingCommandNodes.length > 0 ? (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Pending commands
              </p>
              <pre className="max-h-32 overflow-auto rounded bg-muted/40 p-2 text-[11px] font-mono">
                {JSON.stringify(context.pending_commands, null, 2)}
              </pre>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
