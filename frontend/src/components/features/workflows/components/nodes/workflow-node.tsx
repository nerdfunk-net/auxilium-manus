"use client";

import { createElement, useEffect, type CSSProperties } from "react";
import {
  Handle,
  Position,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { Info, Settings2, Split } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";

import { useWorkflowBuilderStore } from "../../hooks/use-workflow-builder-store";
import type { HandleSide, WorkflowCanvasNode } from "../../types/workflow-canvas";
import {
  CATEGORY_BORDER_FALLBACK,
  CATEGORY_TILE_FALLBACK,
  categoryBorderAccentClasses,
  categoryTileClasses as nodeAccentClassesByType,
  outcomeClasses,
  outcomeHandleClasses,
  resolveStepIcon as resolveNodeIcon,
} from "../../utils/step-visuals";

const NODE_WIDTH_CLASS = "w-80";
const NODE_HEIGHT_CLASS = "h-32";

const TARGET_HANDLE_CLASS =
  "!size-3 !border-2 !bg-muted-foreground/40 !border-muted-foreground";
const GROUP_ENTRY_HANDLE_CLASS =
  "!size-3 !border-2 !bg-step !border-step-hover";
const GROUP_EXIT_HANDLE_RING_CLASS = "!ring-2 !ring-step !ring-offset-1";

const HANDLE_SIDE_TO_POSITION: Record<HandleSide, Position> = {
  top: Position.Top,
  bottom: Position.Bottom,
  left: Position.Left,
  right: Position.Right,
};

function isHorizontalSide(side: HandleSide): boolean {
  return side === "top" || side === "bottom";
}

/** Centers a handle along the axis perpendicular to the side it attaches to. */
function centeringStyle(side: HandleSide): CSSProperties {
  return isHorizontalSide(side) ? { left: "50%" } : { top: "50%" };
}

/** Positions a handle/label at `offsetPct` along the side it attaches to. */
function offsetStyle(side: HandleSide, offsetPct: string): CSSProperties {
  return isHorizontalSide(side) ? { left: offsetPct } : { top: offsetPct };
}

const CONTENT_PADDING_CLASS: Record<HandleSide, { withLabels: string; withoutLabels: string }> = {
  right: { withLabels: "pr-24", withoutLabels: "pr-10" },
  left: { withLabels: "pl-24", withoutLabels: "pl-10" },
  bottom: { withLabels: "pb-8", withoutLabels: "pb-4" },
  top: { withLabels: "pt-8", withoutLabels: "pt-4" },
};

const LABEL_POSITION_CLASS: Record<HandleSide, string> = {
  right: "right-4 -translate-y-1/2",
  left: "left-4 -translate-y-1/2",
  bottom: "bottom-4 -translate-x-1/2",
  top: "top-4 -translate-x-1/2",
};

export function WorkflowNode({ id, data, selected }: NodeProps<WorkflowCanvasNode>) {
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const activeRunId = useWorkflowBuilderStore((state) => state.activeRunId);
  const { data: activeRun } = useWorkflowRunQuery(activeRunId);
  const isAwaitingThisStep =
    activeRun?.status === "paused" && activeRun.current_node_id === id;
  const nodeType = data.artifactType ?? data.kind;
  const hasTargetHandles = (data.requires?.length ?? 0) > 0;
  const outcomes = data.outcomes ?? [];
  const hasSourceHandles = outcomes.length > 0;
  const incomeSide = data.incomeHandleSide ?? "left";
  const outcomeSide = data.outcomeHandleSide ?? "right";
  const fanOut = data.pluginConfig?.fan_out;
  const fanOutEnabled =
    !!fanOut &&
    typeof fanOut === "object" &&
    (fanOut as Record<string, unknown>).enabled === true;
  const showOutcomeLabels = outcomes.length > 1;

  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [
    id,
    updateNodeInternals,
    incomeSide,
    outcomeSide,
    hasTargetHandles,
    hasSourceHandles,
    outcomes.length,
  ]);

  return (
    <div
      className={cn(
        "group relative rounded-xl border border-l-[3px] bg-card shadow-sm transition-shadow",
        NODE_WIDTH_CLASS,
        NODE_HEIGHT_CLASS,
        categoryBorderAccentClasses[nodeType] ?? CATEGORY_BORDER_FALLBACK,
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
        isAwaitingThisStep &&
          "animate-pulse border-step shadow-lg ring-2 ring-step/50",
      )}
    >
      {hasTargetHandles ? (
        <Handle
          className={data.isGroupEntryPoint ? GROUP_ENTRY_HANDLE_CLASS : TARGET_HANDLE_CLASS}
          id="input"
          position={HANDLE_SIDE_TO_POSITION[incomeSide]}
          style={centeringStyle(incomeSide)}
          type="target"
        />
      ) : null}
      <Button
        aria-label="Open configuration"
        className="absolute right-1.5 top-1.5 size-6 opacity-0 transition-opacity group-hover:opacity-100"
        onClick={(event) => {
          event.stopPropagation();
          openConfigModal(id);
        }}
        size="icon"
        variant="ghost"
      >
        <Settings2 className="size-3.5" />
      </Button>
      <div
        className={cn(
          "flex h-full items-start gap-3 p-4",
          showOutcomeLabels
            ? CONTENT_PADDING_CLASS[outcomeSide].withLabels
            : CONTENT_PADDING_CLASS[outcomeSide].withoutLabels,
        )}
      >
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg",
            nodeAccentClassesByType[nodeType] ?? CATEGORY_TILE_FALLBACK,
          )}
        >
          {createElement(resolveNodeIcon(data.kind, nodeType), {
            className: "size-5",
            "aria-hidden": true,
          })}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <p className="min-w-0 text-sm font-semibold leading-snug">{data.title}</p>
            {data.kind === "fan-in" ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info
                    className="mt-0.5 size-3 shrink-0 cursor-help text-muted-foreground"
                    aria-label="About Fan In"
                  />
                </TooltipTrigger>
                <TooltipContent side="top">{data.description}</TooltipContent>
              </Tooltip>
            ) : null}
            {fanOutEnabled ? (
              <Badge
                className="shrink-0 gap-1 border-step-border bg-step-surface text-step-muted-foreground"
                variant="outline"
              >
                <Split className="size-3" aria-hidden />
                Fan out
              </Badge>
            ) : null}
            {isAwaitingThisStep ? (
              <Badge
                className="shrink-0 animate-pulse border-step bg-step-surface text-step-surface-foreground"
                variant="outline"
              >
                Next Step
              </Badge>
            ) : null}
            {data.isGroupEntryPoint ? (
              <Badge
                className="shrink-0 border-step-border bg-step-surface text-step-muted-foreground"
                variant="outline"
              >
                Group input
              </Badge>
            ) : null}
            {data.isGroupExitPoint ? (
              <Badge
                className="shrink-0 border-step-border bg-step-surface text-step-muted-foreground"
                variant="outline"
              >
                Group output
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-2 overflow-hidden text-xs leading-5 text-muted-foreground">
            {data.overview ?? data.description}
          </p>
        </div>
      </div>
      {hasSourceHandles
        ? outcomes.map((outcome, index) => {
            const offsetPct = `${((index + 1) / (outcomes.length + 1)) * 100}%`;
            return (
              <div key={outcome.name}>
                {showOutcomeLabels ? (
                  <span
                    className={cn(
                      "absolute rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                      LABEL_POSITION_CLASS[outcomeSide],
                      outcomeClasses(outcome.name),
                    )}
                    style={offsetStyle(outcomeSide, offsetPct)}
                  >
                    {outcome.name}
                  </span>
                ) : null}
                <Handle
                  className={cn(
                    "!size-3 !border-2",
                    outcomeHandleClasses(outcome.name),
                    data.groupExitHandle === outcome.name && GROUP_EXIT_HANDLE_RING_CLASS,
                  )}
                  id={outcome.name}
                  position={HANDLE_SIDE_TO_POSITION[outcomeSide]}
                  style={offsetStyle(outcomeSide, offsetPct)}
                  type="source"
                />
              </div>
            );
          })
        : null}
    </div>
  );
}
