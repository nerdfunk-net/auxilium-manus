"use client";

import { Activity, CheckCircle2, Clock, Grid3x3, LayoutGrid, Magnet, MoveHorizontal, MoveVertical, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";
import { cn } from "@/lib/utils";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

const ACTIVE_RUN_STATUSES = new Set(["pending", "running", "paused"]);

interface WorkflowRunControlsProps {
  onAutoLayout: () => void;
  isAutoLayoutRunning?: boolean;
}

export function WorkflowRunControls({
  onAutoLayout,
  isAutoLayoutRunning = false,
}: WorkflowRunControlsProps) {
  const workflowStatus = useWorkflowBuilderStore((state) => state.workflowStatus);
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const lastAction = useWorkflowBuilderStore((state) => state.lastAction);
  const activeRunId = useWorkflowBuilderStore((state) => state.activeRunId);
  const autoLayoutDirection = useWorkflowBuilderStore((state) => state.autoLayoutDirection);
  const setAutoLayoutDirection = useWorkflowBuilderStore(
    (state) => state.setAutoLayoutDirection,
  );
  const snapToGrid = useWorkflowBuilderStore((state) => state.snapToGrid);
  const setSnapToGrid = useWorkflowBuilderStore((state) => state.setSnapToGrid);
  const showGrid = useWorkflowBuilderStore((state) => state.showGrid);
  const setShowGrid = useWorkflowBuilderStore((state) => state.setShowGrid);
  const { data: activeRun } = useWorkflowRunQuery(activeRunId);

  let label: string;
  let Icon: LucideIcon;

  if (workflowStatus === "Error") {
    label = lastAction;
    Icon = XCircle;
  } else if (activeRun && ACTIVE_RUN_STATUSES.has(activeRun.status)) {
    label = "Running";
    Icon = Activity;
  } else if (activeRun?.status === "success") {
    label = "Last run was successful";
    Icon = CheckCircle2;
  } else if (activeRun?.status === "failed") {
    label = "Last run failed";
    Icon = XCircle;
  } else if (activeRun?.status === "cancelled") {
    label = "Last run was cancelled";
    Icon = XCircle;
  } else {
    label = workflowStatus;
    Icon = Clock;
  }

  const statusText = isDirty && label !== "Draft" ? `${label} · Draft` : label;

  return (
    <footer className="flex h-12 items-center justify-between border-t bg-card px-5 text-xs text-muted-foreground">
      <span className="flex items-center gap-2">
        <Icon className="size-4" />
        {statusText}
      </span>

      <span className="flex items-center gap-1.5">
        <button
          aria-label="Show grid"
          aria-pressed={showGrid}
          className={cn(
            "flex items-center justify-center rounded-[7px] border p-1.5 transition-colors",
            showGrid
              ? "border-ring bg-muted text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setShowGrid(!showGrid)}
          title="Show the alignment grid"
          type="button"
        >
          <Grid3x3 className="size-3.5" aria-hidden />
        </button>
        <button
          aria-label="Snap to grid"
          aria-pressed={snapToGrid}
          className={cn(
            "flex items-center justify-center rounded-[7px] border p-1.5 transition-colors",
            snapToGrid
              ? "border-ring bg-muted text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setSnapToGrid(!snapToGrid)}
          title="Snap to grid while dragging"
          type="button"
        >
          <Magnet className="size-3.5" aria-hidden />
        </button>
        <div className="mx-0.5 h-4 w-px bg-border" />
        <div className="flex rounded-[7px] border p-[2px]">
          <button
            aria-label="Horizontal layout direction"
            className={cn(
              "flex items-center justify-center rounded-[5px] p-1 transition-colors",
              autoLayoutDirection === "horizontal"
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setAutoLayoutDirection("horizontal")}
            title="Horizontal layout direction"
            type="button"
          >
            <MoveHorizontal className="size-3.5" aria-hidden />
          </button>
          <button
            aria-label="Vertical layout direction"
            className={cn(
              "flex items-center justify-center rounded-[5px] p-1 transition-colors",
              autoLayoutDirection === "vertical"
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setAutoLayoutDirection("vertical")}
            title="Vertical layout direction"
            type="button"
          >
            <MoveVertical className="size-3.5" aria-hidden />
          </button>
        </div>
        <Button
          className="h-7 gap-1.5"
          disabled={isAutoLayoutRunning}
          onClick={onAutoLayout}
          size="sm"
          title="Lay out everything in the current view"
          variant="outline"
        >
          <LayoutGrid className="size-3.5" aria-hidden />
          {isAutoLayoutRunning ? "Laying out…" : "Auto layout"}
        </Button>
      </span>
    </footer>
  );
}
