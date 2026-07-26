"use client";

import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { useWorkflowRunsQuery } from "@/hooks/queries/use-workflow-runs-query";
import {
  useBulkDeleteRunsMutation,
  useCancelRunMutation,
  useDeleteRunMutation,
} from "@/hooks/queries/use-workflow-run-mutations";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";
import { RunListColumn } from "./run-list-column";
import { RunDetailPane } from "./run-detail-pane";
import { DeleteRunDialog } from "../dialogs/delete-run-dialog";
import {
  EMPTY_WORKFLOW_RUN_FILTERS,
  hasActiveWorkflowRunFilters,
} from "../types/workflow-run-filters";
import type { WorkflowRunListFilters } from "../types/workflow-run-filters";
import { TERMINAL_RUN_STATUSES } from "../types/workflow-runs";
import type { WorkflowRunSummary } from "../types/workflow-runs";

const EMPTY_RUNS: WorkflowRunSummary[] = [];

type DeleteDialogState = { type: "single"; runId: number } | { type: "bulk" } | { type: "closed" };

interface WorkflowExecutionsPanelProps {
  onFocusNodeOnCanvas?: (nodeId: string) => void;
}

export function WorkflowExecutionsPanel({ onFocusNodeOnCanvas }: WorkflowExecutionsPanelProps) {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const user = useAuthStore((state) => state.user);
  const canDelete = hasPermission(user, "workflow_runs", "delete");

  const [filters, setFilters] = useState<WorkflowRunListFilters>(EMPTY_WORKFLOW_RUN_FILTERS);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [selectedForDeleteRaw, setSelectedForDeleteRaw] = useState<Set<number>>(new Set());
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState>({ type: "closed" });

  const { data, isLoading, isFetching } = useWorkflowRunsQuery(workflowId, { filters });
  const runs = data?.runs ?? EMPTY_RUNS;
  const filtersActive = hasActiveWorkflowRunFilters(filters);

  const cancelRun = useCancelRunMutation(workflowId);
  const deleteRun = useDeleteRunMutation(workflowId);
  const bulkDeleteRuns = useBulkDeleteRunsMutation(workflowId);

  // Derived (not stored) so the list's background poll can never "steal"
  // selection back to a newly arrived run: this only falls back to the first
  // run when nothing is selected yet, or the selected run has disappeared
  // (filtered out or deleted).
  const effectiveSelectedRunId =
    selectedRunId != null && runs.some((run) => run.id === selectedRunId)
      ? selectedRunId
      : (runs[0]?.id ?? null);

  // Likewise, silently exclude any selected-for-delete ids that no longer
  // exist in the current (possibly re-filtered) list.
  const selectedForDelete = useMemo(
    () => new Set([...selectedForDeleteRaw].filter((id) => runs.some((run) => run.id === id))),
    [selectedForDeleteRaw, runs],
  );

  const toggleSelectForDelete = (runId: number, checked: boolean) => {
    setSelectedForDeleteRaw((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(runId);
      } else {
        next.delete(runId);
      }
      return next;
    });
  };

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedForDeleteRaw(new Set());
      return;
    }
    const deletable = runs.filter((run) => TERMINAL_RUN_STATUSES.includes(run.status));
    setSelectedForDeleteRaw(new Set(deletable.map((run) => run.id)));
  };

  const dialogRunIds =
    deleteDialog.type === "single"
      ? [deleteDialog.runId]
      : deleteDialog.type === "bulk"
        ? Array.from(selectedForDelete)
        : [];
  const isDeleting = deleteRun.isPending || bulkDeleteRuns.isPending;

  const handleConfirmDelete = async () => {
    if (deleteDialog.type === "single") {
      await deleteRun.mutateAsync(deleteDialog.runId);
    } else if (deleteDialog.type === "bulk") {
      await bulkDeleteRuns.mutateAsync(Array.from(selectedForDelete));
      setSelectedForDeleteRaw(new Set());
    }
    setDeleteDialog({ type: "closed" });
  };

  if (workflowId == null) return null;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-slate-50">
      <div className="flex items-center justify-between border-b bg-background px-6 py-4">
        <div>
          <p className="text-sm font-semibold">Executions</p>
          <p className="text-xs text-muted-foreground">
            {isLoading ? "Loading…" : `${data?.total ?? 0} run${data?.total === 1 ? "" : "s"}`}
            {filtersActive ? " (filtered)" : ""}
          </p>
        </div>
        {(isLoading || isFetching) && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
      </div>

      <div className="flex min-h-0 flex-1">
        <RunListColumn
          runs={runs}
          isLoading={isLoading}
          filtersActive={filtersActive}
          filters={filters}
          onFiltersChange={setFilters}
          selectedRunId={effectiveSelectedRunId}
          onSelectRun={setSelectedRunId}
          selectedForDelete={selectedForDelete}
          onToggleSelectForDelete={toggleSelectForDelete}
          onToggleSelectAll={toggleSelectAll}
          onBulkDeleteClick={() => setDeleteDialog({ type: "bulk" })}
          canDelete={canDelete}
          cancellingRunId={cancelRun.isPending ? (cancelRun.variables ?? null) : null}
          onDeleteRun={(runId) => setDeleteDialog({ type: "single", runId })}
          onCancelRun={(runId) => cancelRun.mutate(runId)}
        />
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">
          <RunDetailPane
            runId={effectiveSelectedRunId}
            workflowId={workflowId}
            onFocusCanvas={onFocusNodeOnCanvas}
          />
        </div>
      </div>

      <DeleteRunDialog
        open={deleteDialog.type !== "closed"}
        runIds={dialogRunIds}
        isDeleting={isDeleting}
        onClose={() => setDeleteDialog({ type: "closed" })}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
