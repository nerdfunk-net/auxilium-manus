"use client";

import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  Group,
  MoveHorizontal,
  MoveVertical,
  Sparkles,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";
import type { ProjectedCanvasNode } from "../types/workflow-canvas";

interface MultiStepLayoutPanelProps {
  nodes: ProjectedCanvasNode[];
  canGroup?: boolean;
  autoLayoutDirection: AutoLayoutDirection;
  isAutoLayoutRunning?: boolean;
  onAlign: (alignment: NodeAlignment) => void;
  onAutoLayoutDirectionChange: (direction: AutoLayoutDirection) => void;
  onAutoLayout: () => void;
  onDelete: () => void;
  onGroup?: () => void;
}

type AlignmentAction = {
  alignment: NodeAlignment;
  label: string;
  shortLabel: string;
  icon: typeof AlignStartHorizontal;
};

const ALIGN_ACTIONS: AlignmentAction[] = [
  { alignment: "align-left", label: "Align left", shortLabel: "Left", icon: AlignStartVertical },
  {
    alignment: "align-center-horizontal",
    label: "Center horizontally",
    shortLabel: "Center",
    icon: AlignCenterVertical,
  },
  { alignment: "align-right", label: "Align right", shortLabel: "Right", icon: AlignEndVertical },
  { alignment: "align-top", label: "Align top", shortLabel: "Top", icon: AlignStartHorizontal },
  {
    alignment: "align-center-vertical",
    label: "Center vertically",
    shortLabel: "Middle",
    icon: AlignCenterHorizontal,
  },
  { alignment: "align-bottom", label: "Align bottom", shortLabel: "Bottom", icon: AlignEndHorizontal },
];

const DISTRIBUTE_ACTIONS: AlignmentAction[] = [
  {
    alignment: "distribute-horizontal",
    label: "Distribute horizontally",
    shortLabel: "Horizontal",
    icon: AlignHorizontalDistributeCenter,
  },
  {
    alignment: "distribute-vertical",
    label: "Distribute vertically",
    shortLabel: "Vertical",
    icon: AlignVerticalDistributeCenter,
  },
];

export function MultiStepLayoutPanel({
  nodes,
  canGroup = false,
  autoLayoutDirection,
  isAutoLayoutRunning = false,
  onAlign,
  onAutoLayoutDirectionChange,
  onAutoLayout,
  onDelete,
  onGroup,
}: MultiStepLayoutPanelProps) {
  const canDistribute = nodes.length >= 3;

  return (
    <div>
      <p className="text-[13px] font-semibold">{nodes.length} steps selected</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Align and distribute the selected steps.
      </p>

      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Align
      </p>
      <div className="mt-2.5 grid grid-cols-3 gap-1.5">
        {ALIGN_ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <Button
              className="h-8 justify-start gap-1 px-1.5 text-[10px]"
              key={action.alignment}
              onClick={() => onAlign(action.alignment)}
              size="sm"
              title={action.label}
              variant="outline"
            >
              <Icon className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{action.shortLabel}</span>
            </Button>
          );
        })}
      </div>

      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Distribute
      </p>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        {DISTRIBUTE_ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <Button
              className="h-8 justify-start gap-1 px-1.5 text-[10px]"
              disabled={!canDistribute}
              key={action.alignment}
              onClick={() => onAlign(action.alignment)}
              size="sm"
              title={action.label}
              variant="outline"
            >
              <Icon className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{action.shortLabel}</span>
            </Button>
          );
        })}
      </div>
      {!canDistribute ? (
        <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
          Distribute needs at least three selected steps.
        </p>
      ) : null}

      <p className="mt-4 text-[11px] font-semibold uppercase tracking-[.05em] text-muted-foreground">
        Auto layout
      </p>
      <div className="mt-2.5 flex gap-1.5">
        <div className="flex flex-1 rounded-[9px] border p-[3px]">
          <button
            className={cn(
              "flex flex-1 items-center justify-center gap-1 rounded-[6px] py-1 text-[10px] font-medium transition-colors",
              autoLayoutDirection === "horizontal"
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onAutoLayoutDirectionChange("horizontal")}
            title="Horizontal"
            type="button"
          >
            <MoveHorizontal className="size-3" aria-hidden />
            Horizontal
          </button>
          <button
            className={cn(
              "flex flex-1 items-center justify-center gap-1 rounded-[6px] py-1 text-[10px] font-medium transition-colors",
              autoLayoutDirection === "vertical"
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onAutoLayoutDirectionChange("vertical")}
            title="Vertical"
            type="button"
          >
            <MoveVertical className="size-3" aria-hidden />
            Vertical
          </button>
        </div>
      </div>
      <Button
        className="mt-2 w-full gap-1.5"
        disabled={nodes.length < 2 || isAutoLayoutRunning}
        onClick={onAutoLayout}
        size="sm"
        variant="outline"
      >
        <Sparkles className="size-3.5" aria-hidden />
        {isAutoLayoutRunning ? "Laying out…" : "Tidy this branch"}
      </Button>

      {canGroup ? (
        <Button
          className="mt-4 w-full gap-1.5"
          onClick={onGroup}
          size="sm"
          variant="outline"
        >
          <Group className="size-3.5" aria-hidden />
          Group selected steps
        </Button>
      ) : null}

      <Button
        className="mt-2 w-full gap-1.5 border-destructive/30 text-destructive hover:bg-destructive/5 hover:text-destructive"
        onClick={onDelete}
        size="sm"
        variant="outline"
      >
        <Trash2 className="size-3.5" aria-hidden />
        Delete {nodes.length} steps
      </Button>
    </div>
  );
}
