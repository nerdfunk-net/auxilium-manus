"use client";

import { useMemo } from "react";

import { getAncestorNodeIds } from "@/components/features/workflows/utils/attribute-path-ancestors";
import { useWorkflowBuilderStore } from "@/components/features/workflows/hooks/use-workflow-builder-store";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import { useAttributePathResolveQuery } from "@/hooks/queries/use-attribute-path-resolve-query";
import { useWorkflowRunsQuery } from "@/hooks/queries/use-workflow-runs-query";
import type { AttributeState } from "@/lib/attribute-path-types";

/**
 * Step-agnostic live preview: resolves whatever `path` is currently typed
 * against the workflow's most recent run (ancestor steps only), the same way
 * `AttributePathPicker` does. Works off the live text value, not just paths
 * chosen from the picker, so a hand-edited path gets the same feedback.
 */
export interface AttributePathPreviewProps {
  path: string;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
}

const STATE_LABEL: Record<AttributeState, string> = {
  absent: "absent",
  null: "null",
  empty: "empty",
  present: "present",
};

const MUTED_STATES = new Set<AttributeState>(["absent", "null", "empty"]);

export function AttributePathPreview({
  path,
  nodeId,
  workflowNodes,
  workflowEdges,
}: AttributePathPreviewProps) {
  const trimmedPath = path.trim();
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);

  const { data: runsData } = useWorkflowRunsQuery(trimmedPath ? workflowId : null);
  const runId = runsData?.runs[0]?.id ?? null;

  const ancestorNodeIds = useMemo(
    () => Array.from(getAncestorNodeIds(nodeId, workflowNodes, workflowEdges)),
    [nodeId, workflowNodes, workflowEdges],
  );

  const { data, isFetching } = useAttributePathResolveQuery(runId, ancestorNodeIds, trimmedPath, {
    enabled: trimmedPath.length > 0,
  });

  if (!trimmedPath) {
    return null;
  }
  if (!workflowId || !runId) {
    return (
      <p className="text-[11px] text-muted-foreground">
        Run this workflow at least once to preview resolved values here.
      </p>
    );
  }
  if (isFetching && !data) {
    return <p className="text-[11px] text-muted-foreground">Resolving…</p>;
  }
  if (!data || data.results.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        {ancestorNodeIds.length === 0
          ? "This step has no upstream connection in the canvas yet."
          : `No upstream step has output in run #${runId} (the most recent one) — run the workflow again.`}
      </p>
    );
  }

  return (
    <div className="space-y-1 rounded border bg-muted/30 p-2">
      {data.results.map((result) => (
        <div key={result.device_id} className="flex items-center gap-2 text-[11px]">
          <span className="w-28 shrink-0 truncate font-medium">{result.device_name}</span>
          <span
            className={MUTED_STATES.has(result.state) ? "shrink-0 text-muted-foreground" : "shrink-0"}
          >
            {STATE_LABEL[result.state]}
          </span>
          {result.value !== null ? (
            <span className="truncate font-mono text-muted-foreground">{result.value}</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}
