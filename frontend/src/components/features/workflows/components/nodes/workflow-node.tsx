"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Info, Settings2, Split } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../../hooks/use-workflow-builder-store";
import type { WorkflowCanvasNode } from "../../types/workflow-canvas";
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
  "!size-3 !border-2 !bg-slate-300 !border-slate-400";

export function WorkflowNode({ id, data, selected }: NodeProps<WorkflowCanvasNode>) {
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const nodeType = data.artifactType ?? data.kind;
  const Icon = resolveNodeIcon(data.kind, nodeType);
  const hasTargetHandles = (data.requires?.length ?? 0) > 0;
  const outcomes = data.outcomes ?? [];
  const hasSourceHandles = outcomes.length > 0;
  const fanOut = data.pluginConfig?.fan_out;
  const fanOutEnabled =
    !!fanOut &&
    typeof fanOut === "object" &&
    (fanOut as Record<string, unknown>).enabled === true;
  const showOutcomeLabels = outcomes.length > 1;

  return (
    <div
      className={cn(
        "group relative rounded-xl border border-l-[3px] bg-card shadow-sm transition-shadow",
        NODE_WIDTH_CLASS,
        NODE_HEIGHT_CLASS,
        categoryBorderAccentClasses[nodeType] ?? CATEGORY_BORDER_FALLBACK,
        selected && "border-ring shadow-lg ring-2 ring-ring/20",
      )}
    >
      {hasTargetHandles ? (
        <Handle
          className={TARGET_HANDLE_CLASS}
          id="input"
          position={Position.Left}
          style={{ top: "50%" }}
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
          showOutcomeLabels ? "pr-24" : "pr-10",
        )}
      >
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg",
            nodeAccentClassesByType[nodeType] ?? CATEGORY_TILE_FALLBACK,
          )}
        >
          <Icon className="size-5" aria-hidden />
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
                className="shrink-0 gap-1 border-teal-300 bg-teal-50 text-teal-700"
                variant="outline"
              >
                <Split className="size-3" aria-hidden />
                Fan out
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-2 overflow-hidden text-xs leading-5 text-muted-foreground">
            {data.description}
          </p>
        </div>
      </div>
      {hasSourceHandles
        ? outcomes.map((outcome, index) => (
            <div key={outcome.name}>
              {showOutcomeLabels ? (
                <span
                  className={cn(
                    "absolute right-4 -translate-y-1/2 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                    outcomeClasses(outcome.name),
                  )}
                  style={{
                    top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                  }}
                >
                  {outcome.name}
                </span>
              ) : null}
              <Handle
                className={cn("!size-3 !border-2", outcomeHandleClasses(outcome.name))}
                id={outcome.name}
                position={Position.Right}
                style={{
                  top: `${((index + 1) / (outcomes.length + 1)) * 100}%`,
                }}
                type="source"
              />
            </div>
          ))
        : null}
    </div>
  );
}
