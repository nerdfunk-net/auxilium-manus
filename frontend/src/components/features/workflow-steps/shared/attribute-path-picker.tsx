"use client";

import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type React from "react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getAncestorNodeIds } from "@/components/features/workflows/utils/attribute-path-ancestors";
import { useWorkflowBuilderStore } from "@/components/features/workflows/hooks/use-workflow-builder-store";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "@/components/features/workflows/types/workflow-canvas";
import { useAttributePathTreeQuery } from "@/hooks/queries/use-attribute-path-tree-query";
import { useWorkflowRunsQuery } from "@/hooks/queries/use-workflow-runs-query";
import type { AttributePathNode } from "@/lib/attribute-path-types";

/**
 * Step-agnostic attribute path picker: given a node's position in the canvas
 * graph, browses the discoverable attribute paths from the workflow's most
 * recent run, restricted to that node's ancestors. Its only output is a
 * plain `path: string` via `onSelect` — no knowledge of what config field
 * that path will end up in, so any step's config panel can reuse it.
 */
export interface AttributePathPickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  nodeId: string;
  workflowNodes: PersistedCanvasNode[];
  workflowEdges: WorkflowCanvasEdge[];
}

const KIND_BADGE_LABEL: Record<AttributePathNode["kind"], string> = {
  scalar: "value",
  dict: "object",
  list: "list",
};

function matchesSearch(node: AttributePathNode, term: string): boolean {
  if (!term) {
    return true;
  }
  if (node.path.toLowerCase().includes(term) || node.name.toLowerCase().includes(term)) {
    return true;
  }
  return node.children.some((child) => matchesSearch(child, term));
}

function AttributePathTreeNode({
  node,
  term,
  depth,
  onSelect,
}: {
  node: AttributePathNode;
  term: string;
  depth: number;
  onSelect: (path: string) => void;
}) {
  // Dict/scalar nodes auto-expand regardless of depth, so a chain like
  // parsed → batfish_extract_facts → parsed → TACACS is fully visible without
  // clicking through each wrapper level. Only `list` nodes default collapsed,
  // since a discriminated list can expand into up to MAX_LIST_ITEM_BRANCHES
  // per-item branches.
  const [expanded, setExpanded] = useState(node.kind !== "list");
  if (!matchesSearch(node, term)) {
    return null;
  }

  const hasChildren = node.children.length > 0;
  const isExpanded = term.length > 0 || expanded;

  return (
    <div>
      <div
        className="flex w-max min-w-full items-center gap-1.5 rounded px-1 py-1 hover:bg-muted"
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="shrink-0 text-muted-foreground"
            aria-label={isExpanded ? "Collapse" : "Expand"}
          >
            {isExpanded ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </button>
        ) : (
          <span className="inline-block size-3 shrink-0" />
        )}
        <button
          type="button"
          onClick={() => onSelect(node.path)}
          className="flex items-center gap-2 text-left"
          title={node.path}
        >
          <span className="whitespace-nowrap font-mono text-xs">{node.name}</span>
          <Badge className="h-4 shrink-0 rounded px-1 text-[10px]" variant="secondary">
            {KIND_BADGE_LABEL[node.kind]}
            {node.item_count !== null ? ` (${node.item_count})` : ""}
          </Badge>
          {node.example_value !== null ? (
            <span className="whitespace-nowrap text-[11px] text-muted-foreground">
              {node.example_value}
            </span>
          ) : null}
          {node.discriminator_warning ? (
            <span
              className="shrink-0 text-[10px] text-amber-600"
              title={node.discriminator_warning}
            >
              ⚠
            </span>
          ) : null}
        </button>
      </div>
      {hasChildren && isExpanded ? (
        <div>
          {node.children.map((child) => (
            <AttributePathTreeNode
              key={child.path}
              node={child}
              term={term}
              depth={depth + 1}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function AttributePathPicker({
  open,
  onClose,
  onSelect,
  nodeId,
  workflowNodes,
  workflowEdges,
}: AttributePathPickerProps) {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const [search, setSearch] = useState("");

  // Gate the runs query on `open` (rather than an `enabled` option this hook
  // doesn't expose) so it doesn't fetch/poll while the picker is closed.
  const { data: runsData, isLoading: runsLoading } = useWorkflowRunsQuery(
    open ? workflowId : null,
  );
  const runId = runsData?.runs[0]?.id ?? null;

  const ancestorNodeIds = useMemo(
    () => Array.from(getAncestorNodeIds(nodeId, workflowNodes, workflowEdges)),
    [nodeId, workflowNodes, workflowEdges],
  );

  const { data: treeData, isLoading: treeLoading } = useAttributePathTreeQuery(
    runId,
    ancestorNodeIds,
    { enabled: open },
  );

  const handleSelect = (path: string) => {
    onSelect(path);
    onClose();
  };

  const term = search.trim().toLowerCase();
  const nodes = treeData?.nodes ?? [];
  const visibleNodes = nodes.filter((node) => matchesSearch(node, term));

  let body: React.ReactNode;
  if (!workflowId) {
    body = (
      <p className="text-sm text-muted-foreground">
        Save this workflow first, then run it at least once, to browse real attribute values
        here.
      </p>
    );
  } else if (runsLoading) {
    body = <p className="text-sm text-muted-foreground">Loading runs…</p>;
  } else if (!runId) {
    body = (
      <p className="text-sm text-muted-foreground">
        Run this workflow at least once to browse real attribute values here.
      </p>
    );
  } else if (treeLoading) {
    body = <p className="text-sm text-muted-foreground">Loading attributes…</p>;
  } else if (treeData && treeData.device_count === 0) {
    // The "device" namespace always renders (even with no devices), so this
    // must be checked explicitly — otherwise a stale/disconnected sample run
    // silently looks like an empty tree with no explanation.
    body = (
      <div className="space-y-1 text-sm text-muted-foreground">
        <p>No device data available from this step&apos;s upstream steps yet.</p>
        {ancestorNodeIds.length === 0 ? (
          <p className="text-[11px]">
            This step has no upstream connection in the canvas — connect it after a step that
            produces device data.
          </p>
        ) : (
          <p className="text-[11px]">
            Found {ancestorNodeIds.length} upstream step{ancestorNodeIds.length === 1 ? "" : "s"}
            , but none has output in run #{treeData.run_id} (the most recent one). Run the
            workflow again after wiring up those steps.
          </p>
        )}
      </div>
    );
  } else if (visibleNodes.length === 0) {
    body = (
      <p className="text-sm text-muted-foreground">
        {nodes.length === 0
          ? "No attributes found from steps upstream of this one in the most recent run."
          : "No attribute paths match your search."}
      </p>
    );
  } else {
    body = (
      <div className="max-h-80 overflow-auto rounded border">
        {visibleNodes.map((node) => (
          <AttributePathTreeNode
            key={node.path}
            node={node}
            term={term}
            depth={0}
            onSelect={handleSelect}
          />
        ))}
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Browse attributes</DialogTitle>
          <DialogDescription>
            Paths discovered from the workflow&apos;s most recent run, limited to steps upstream
            of this one. Click a path to use it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-1">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter paths…"
              className="h-8 pl-7 text-xs"
            />
          </div>
          {body}
        </div>
      </DialogContent>
    </Dialog>
  );
}
