"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { ArtifactRef } from "@/lib/workflow-context-types";

import { ConfigArtifactPanel } from "./config-artifact-panel";

/** Key batfish-init-snapshot writes into WorkflowContext.metadata (host/port/network/snapshot). */
export const BATFISH_CONNECTION_METADATA_KEY = "batfish";

export interface BatfishConnectionInfo {
  host: string;
  port: number;
  network: string;
  snapshot: string;
}

export interface BatfishResultEntry {
  key: string;
  question: string;
  artifactRef: ArtifactRef;
  rowCount?: number;
  reachable?: boolean;
  action?: string;
}

function isBatfishConnectionInfo(value: unknown): value is BatfishConnectionInfo {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as BatfishConnectionInfo).host === "string" &&
    typeof (value as BatfishConnectionInfo).network === "string" &&
    typeof (value as BatfishConnectionInfo).snapshot === "string"
  );
}

interface RawBatfishResultPayload {
  kind: string;
  question: string;
  artifact_ref: ArtifactRef;
  row_count?: number;
  reachable?: boolean;
  action?: string;
}

function isBatfishResultPayload(value: unknown): value is RawBatfishResultPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { kind?: unknown }).kind === "batfish_result" &&
    typeof (value as { artifact_ref?: unknown }).artifact_ref === "object" &&
    (value as { artifact_ref?: unknown }).artifact_ref !== null
  );
}

export function extractBatfishConnection(
  metadata: Record<string, unknown>,
): BatfishConnectionInfo | null {
  const raw = metadata[BATFISH_CONNECTION_METADATA_KEY];
  return isBatfishConnectionInfo(raw) ? raw : null;
}

export function extractBatfishResults(metadata: Record<string, unknown>): BatfishResultEntry[] {
  return Object.entries(metadata)
    .filter(([key]) => key !== BATFISH_CONNECTION_METADATA_KEY)
    .filter((entry): entry is [string, RawBatfishResultPayload] => isBatfishResultPayload(entry[1]))
    .map(([key, payload]) => ({
      key,
      question: payload.question,
      artifactRef: payload.artifact_ref,
      rowCount: payload.row_count,
      reachable: payload.reachable,
      action: payload.action,
    }));
}

/** Metadata keys already surfaced by BatfishResultPanel — excluded from the generic Metadata dump. */
export function isBatfishMetadataKey(key: string, value: unknown): boolean {
  return key === BATFISH_CONNECTION_METADATA_KEY || isBatfishResultPayload(value);
}

const QUESTION_LABELS: Record<string, string> = {
  routes: "Routing table",
  reachability: "Path check",
  testFilters: "ACL check",
  validateFacts: "Validate facts",
  extractFacts: "Extract facts",
};

function BatfishResultSummary({ entry }: { entry: BatfishResultEntry }) {
  const label = QUESTION_LABELS[entry.question] ?? entry.question;
  const rowCount = entry.rowCount ?? 0;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium">{label}</span>
      {entry.reachable != null ? (
        <Badge
          className="text-[10px]"
          variant={entry.reachable ? "secondary" : "destructive"}
        >
          {entry.reachable ? "Reachable" : "Not reachable"}
        </Badge>
      ) : null}
      {entry.action ? (
        <Badge
          className="text-[10px]"
          variant={entry.action.toUpperCase() === "PERMIT" ? "secondary" : "destructive"}
        >
          {entry.action}
        </Badge>
      ) : null}
      <span className="text-[11px] text-muted-foreground">
        {rowCount} row{rowCount !== 1 ? "s" : ""}
      </span>
    </div>
  );
}

export function BatfishResultPanel({
  runId,
  results,
  connection,
  expanded = false,
}: {
  runId: number | null;
  results: BatfishResultEntry[];
  connection: BatfishConnectionInfo | null;
  /** Whether each entry's content starts expanded — the user can still
   * collapse/expand any entry individually afterward. */
  expanded?: boolean;
}) {
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(
    () => new Set(expanded ? results.map((entry) => entry.key) : []),
  );

  if (results.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No Batfish result recorded on this outcome path.
      </p>
    );
  }

  const toggleEntry = (key: string) => {
    setExpandedKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <div className="space-y-4">
      {connection ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          {connection.host}:{connection.port} · network {connection.network} · snapshot{" "}
          {connection.snapshot}
        </p>
      ) : null}

      {results.map((entry) => {
        const isExpanded = expandedKeys.has(entry.key);
        return (
          <div key={entry.key} className="space-y-1.5 rounded-lg border bg-card p-3">
            <button
              type="button"
              className="flex w-full min-w-0 items-center gap-1.5 text-left"
              onClick={() => toggleEntry(entry.key)}
              aria-expanded={isExpanded}
            >
              {isExpanded ? (
                <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              ) : (
                <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              )}
              <BatfishResultSummary entry={entry} />
            </button>
            <p className="font-mono text-[10px] text-muted-foreground">{entry.key}</p>
            {entry.rowCount === 0 ? (
              <p className="text-[11px] text-warning-foreground">
                No rows returned — check the step&apos;s filters, or confirm the snapshot&apos;s
                devices actually parsed in Batfish (an unsupported platform or malformed config
                parses to zero routes/nodes).
              </p>
            ) : null}
            {isExpanded ? (
              runId == null ? (
                <p className="text-xs text-muted-foreground">
                  Result content is available from a workflow run detail view.
                </p>
              ) : (
                <ConfigArtifactPanel
                  runId={runId}
                  label="Result"
                  artifactRef={entry.artifactRef}
                  expanded
                />
              )
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
