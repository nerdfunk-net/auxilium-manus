"use client";

import { Loader2, Play, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { WorkflowRunFiltersBar } from "./workflow-run-filters-bar";
import { RunListItem } from "./run-list-item";
import type { WorkflowRunListFilters } from "../types/workflow-run-filters";
import type { WorkflowRunSummary } from "../types/workflow-runs";
import { TERMINAL_RUN_STATUSES } from "../types/workflow-runs";

interface RunListColumnProps {
  runs: WorkflowRunSummary[];
  isLoading: boolean;
  filtersActive: boolean;
  filters: WorkflowRunListFilters;
  onFiltersChange: (filters: WorkflowRunListFilters) => void;
  selectedRunId: number | null;
  onSelectRun: (runId: number) => void;
  selectedForDelete: Set<number>;
  onToggleSelectForDelete: (runId: number, checked: boolean) => void;
  onToggleSelectAll: (checked: boolean) => void;
  onBulkDeleteClick: () => void;
  canDelete: boolean;
  cancellingRunId: number | null;
  onDeleteRun: (runId: number) => void;
  onCancelRun: (runId: number) => void;
}

export function RunListColumn({
  runs,
  isLoading,
  filtersActive,
  filters,
  onFiltersChange,
  selectedRunId,
  onSelectRun,
  selectedForDelete,
  onToggleSelectForDelete,
  onToggleSelectAll,
  onBulkDeleteClick,
  canDelete,
  cancellingRunId,
  onDeleteRun,
  onCancelRun,
}: RunListColumnProps) {
  const deletableRuns = runs.filter((run) => TERMINAL_RUN_STATUSES.includes(run.status));
  const allSelected = deletableRuns.length > 0 && selectedForDelete.size === deletableRuns.length;

  return (
    <div className="flex w-[380px] shrink-0 flex-col border-r bg-muted">
      <WorkflowRunFiltersBar filters={filters} onChange={onFiltersChange} />

      {canDelete && deletableRuns.length > 0 ? (
        <div className="flex items-center justify-between gap-2 border-b bg-background px-4 py-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={allSelected}
              onCheckedChange={(checked) => onToggleSelectAll(checked === true)}
              aria-label="Select all finished runs"
            />
            {selectedForDelete.size > 0 ? `${selectedForDelete.size} selected` : "Select all"}
          </label>
          {selectedForDelete.size > 0 ? (
            <Button
              size="sm"
              variant="destructive"
              className="h-7 gap-1 text-xs"
              onClick={onBulkDeleteClick}
            >
              <Trash2 className="size-3.5" />
              Delete {selectedForDelete.size}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : runs.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4">
            <div className="text-center text-muted-foreground">
              <Play className="mx-auto mb-2 size-8 opacity-30" />
              <p className="text-sm">
                {filtersActive
                  ? "No runs match the current filters."
                  : "No runs yet — click Run to start the workflow."}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            {runs.map((run) => (
              <RunListItem
                key={run.id}
                run={run}
                isActive={selectedRunId === run.id}
                isSelectedForDelete={selectedForDelete.has(run.id)}
                canDelete={canDelete}
                isCancelling={cancellingRunId === run.id}
                onSelect={() => onSelectRun(run.id)}
                onToggleSelectForDelete={(checked) => onToggleSelectForDelete(run.id, checked)}
                onDeleteClick={() => onDeleteRun(run.id)}
                onCancel={() => onCancelRun(run.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
