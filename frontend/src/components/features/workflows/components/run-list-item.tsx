"use client";

import { Ban, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import type { WorkflowRunSummary } from "../types/workflow-runs";
import { TERMINAL_RUN_STATUSES } from "../types/workflow-runs";
import { RunStatusIcon, formatDuration, formatTime } from "./run-status-icon";

interface RunListItemProps {
  run: WorkflowRunSummary;
  isActive: boolean;
  isSelectedForDelete: boolean;
  canDelete: boolean;
  isCancelling: boolean;
  onSelect: () => void;
  onToggleSelectForDelete: (checked: boolean) => void;
  onDeleteClick: () => void;
  onCancel: () => void;
}

export function RunListItem({
  run,
  isActive,
  isSelectedForDelete,
  canDelete,
  isCancelling,
  onSelect,
  onToggleSelectForDelete,
  onDeleteClick,
  onCancel,
}: RunListItemProps) {
  const isTerminal = TERMINAL_RUN_STATUSES.includes(run.status);
  const canCancel = run.status === "pending" || run.status === "running" || run.status === "paused";

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg border px-3 py-2.5 transition-colors",
        isActive ? "border-primary bg-primary/5" : "border-transparent hover:bg-muted/50",
      )}
    >
      {isTerminal && canDelete ? (
        <Checkbox
          checked={isSelectedForDelete}
          onCheckedChange={(checked) => onToggleSelectForDelete(checked === true)}
          aria-label={`Select run #${run.id}`}
        />
      ) : (
        <div className="size-4 shrink-0" />
      )}

      <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={onSelect}>
        <RunStatusIcon status={run.status} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            Run #{run.id}
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {run.uuid.slice(0, 8)}…
            </span>
          </p>
          <p className="text-xs text-muted-foreground">
            {run.triggered_by_username ?? "unknown"} · {formatTime(run.created_at)}
          </p>
          {run.status === "paused" && run.debug_message ? (
            <p className="mt-0.5 truncate text-xs text-amber-700">{run.debug_message}</p>
          ) : null}
        </div>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatDuration(run.started_at, run.finished_at)}
        </span>
      </button>

      {canCancel ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0"
          disabled={isCancelling}
          onClick={onCancel}
          title="Cancel run"
        >
          <Ban className="size-3.5" />
        </Button>
      ) : isTerminal && canDelete ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-muted-foreground hover:text-destructive"
          onClick={onDeleteClick}
          title="Delete run"
        >
          <Trash2 className="size-3.5" />
        </Button>
      ) : null}
    </div>
  );
}
