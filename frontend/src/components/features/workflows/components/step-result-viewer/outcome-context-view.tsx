"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import type { WorkflowContext } from "@/lib/workflow-context-types";

import {
  BatfishResultPanel,
  extractBatfishConnection,
  extractBatfishResults,
} from "./batfish-result-panel";
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
  const batfishResults = useMemo(
    () => extractBatfishResults(context.metadata),
    [context.metadata],
  );
  const batfishConnection = useMemo(
    () => extractBatfishConnection(context.metadata),
    [context.metadata],
  );
  const debugLogs = useMemo(() => extractDebugLogs(context.metadata), [context.metadata]);
  const logAttributes = useMemo(
    () => extractLogAttributes(context.metadata),
    [context.metadata],
  );
  const remainingMetadata = useMemo(
    () => metadataWithoutDebugPanels(context.metadata),
    [context.metadata],
  );
  const metadataCount = Object.keys(remainingMetadata).length;
  const [metadataExpanded, setMetadataExpanded] = useState(false);

  return (
    <div className={cn("min-w-0 overflow-hidden", compact ? "space-y-2" : "space-y-4")}>
      {batfishResults.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Batfish result
          </p>
          <BatfishResultPanel
            runId={runId ?? null}
            results={batfishResults}
            connection={batfishConnection}
            expanded={!compact}
          />
        </div>
      ) : null}

      <DevicesSection
        devices={devices}
        runId={runId}
        compact={compact}
        batfishResults={batfishResults}
        batfishConnection={batfishConnection}
      />

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
          <div className="min-w-0">
            <button
              type="button"
              className="mb-2 flex w-full min-w-0 items-center gap-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
              onClick={() => setMetadataExpanded((value) => !value)}
              aria-expanded={metadataExpanded}
            >
              {metadataExpanded ? (
                <ChevronDown className="size-3.5 shrink-0" aria-hidden />
              ) : (
                <ChevronRight className="size-3.5 shrink-0" aria-hidden />
              )}
              <span>Metadata ({metadataCount})</span>
            </button>

            {metadataExpanded ? <MetadataPanel metadata={remainingMetadata} /> : null}
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
