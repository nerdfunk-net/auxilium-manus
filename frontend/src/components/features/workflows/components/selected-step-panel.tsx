"use client";

import { Copy, FolderOpen, Settings2, Trash2 } from "lucide-react";
import { createElement } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { ProjectedCanvasNode } from "../types/workflow-canvas";
import { isGroupCanvasNode } from "../utils/canvas-group-projection";
import {
  CATEGORY_TILE_FALLBACK,
  categoryTileClasses,
  formatArtifactType,
  outcomeDotClasses,
  resolveStepIcon,
} from "../utils/step-visuals";

function DataContractChips({
  capabilities,
  emptyLabel,
}: {
  capabilities: string[];
  emptyLabel: string;
}) {
  if (capabilities.length === 0) {
    return <span className="text-[11.5px] text-muted-foreground">{emptyLabel}</span>;
  }
  return (
    <>
      {capabilities.map((capability) => (
        <span
          key={capability}
          className="rounded-[6px] border bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground"
        >
          {capability}
        </span>
      ))}
    </>
  );
}

interface SelectedStepPanelProps {
  node: ProjectedCanvasNode;
  onOpenConfig: () => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onDeleteNodes?: (nodeIds: string[]) => void;
  onRenameGroup?: (groupId: string, title: string) => void;
  onUngroupGroup?: (groupId: string) => void;
  onOpenGroup?: (groupId: string) => void;
}

export function SelectedStepPanel({
  node,
  onOpenConfig,
  onNodeTitleChange,
  onDuplicateNode,
  onDeleteNodes,
  onRenameGroup,
  onUngroupGroup,
  onOpenGroup,
}: SelectedStepPanelProps) {
  if (isGroupCanvasNode(node)) {
    return (
      <div>
        <div className="flex items-center gap-3">
          <span className="flex size-[42px] shrink-0 items-center justify-center rounded-lg bg-step-surface text-step-muted-foreground">
            <FolderOpen className="size-[18px]" aria-hidden />
          </span>
          <span className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
            Group
          </span>
        </div>

        <Input
          className="mt-3 h-auto rounded-[9px] p-[9px_11px] text-[15px] font-semibold"
          onChange={(event) => onRenameGroup?.(node.data.groupId, event.target.value)}
          value={node.data.title}
        />
        <p className="mt-3 text-[12.5px] leading-[1.5] text-muted-foreground">
          {node.data.memberCount} step
          {node.data.memberCount === 1 ? "" : "s"} in this group.
        </p>

        <Button className="mt-5 w-full gap-2" onClick={() => onOpenGroup?.(node.data.groupId)}>
          <FolderOpen className="size-4" aria-hidden />
          Open group
        </Button>
        <Button
          className="mt-2 w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
          onClick={() => onUngroupGroup?.(node.data.groupId)}
          variant="outline"
        >
          <Trash2 className="size-3.5" aria-hidden />
          Ungroup
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex size-[42px] shrink-0 items-center justify-center rounded-lg",
            categoryTileClasses[node.data.artifactType ?? node.data.kind] ?? CATEGORY_TILE_FALLBACK,
          )}
        >
          {createElement(
            resolveStepIcon(node.data.kind, node.data.artifactType ?? node.data.kind),
            { className: "size-[18px]", "aria-hidden": true },
          )}
        </span>
        <span className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
          {formatArtifactType(node.data.artifactType ?? node.data.kind)}
        </span>
      </div>

      <Input
        className="mt-3 h-auto rounded-[9px] p-[9px_11px] text-[15px] font-semibold"
        onChange={(event) => onNodeTitleChange?.(node.id, event.target.value)}
        value={node.data.title}
      />
      <p className="mt-3 text-[12.5px] leading-[1.5] text-muted-foreground">
        {node.data.description}
      </p>

      <p className="mt-[18px] text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Data contract
      </p>
      <div className="mt-2.5 space-y-2.5">
        <div>
          <p className="mb-1.5 text-[11.5px] text-muted-foreground">Requires (input)</p>
          <div className="flex flex-wrap gap-1.5">
            <DataContractChips
              capabilities={[...(node.data.requires ?? []), ...(node.data.requiresParsed ?? [])]}
              emptyLabel="None — start step"
            />
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-[11.5px] text-muted-foreground">Produces (output)</p>
          <div className="flex flex-wrap gap-1.5">
            <DataContractChips
              capabilities={[...(node.data.produces ?? []), ...(node.data.producesParsed ?? [])]}
              emptyLabel="Passes context through"
            />
          </div>
        </div>
      </div>

      {(node.data.outcomes?.length ?? 0) > 0 ? (
        <>
          <p className="mt-[18px] text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
            Outcomes
          </p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {node.data.outcomes?.map((outcome) => (
              <span
                key={outcome.name}
                className="flex items-center gap-1.5 rounded-full border bg-muted/50 px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
              >
                <span
                  className={cn("size-1.5 rounded-full", outcomeDotClasses(outcome.name))}
                />
                {outcome.name}
              </span>
            ))}
          </div>
        </>
      ) : null}

      <Button className="mt-5 w-full gap-2" onClick={onOpenConfig}>
        <Settings2 className="size-4" aria-hidden />
        Open configuration
      </Button>
      <div className="mt-2 flex gap-2">
        <Button
          className="flex-1 gap-1.5"
          onClick={() => onDuplicateNode?.(node.id)}
          variant="outline"
        >
          <Copy className="size-3.5" aria-hidden />
          Duplicate
        </Button>
        <Button
          className="flex-1 gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
          onClick={() => onDeleteNodes?.([node.id])}
          variant="outline"
        >
          <Trash2 className="size-3.5" aria-hidden />
          Delete
        </Button>
      </div>
    </div>
  );
}
