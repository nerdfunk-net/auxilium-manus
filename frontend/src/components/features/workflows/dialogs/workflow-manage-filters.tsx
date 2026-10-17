"use client";

import type { WorkflowSummary } from "../types/workflow-persistence";
import { DeleteConfirmRow, WorkflowRow } from "./workflow-manage-row";

interface WorkflowManageFiltersProps {
  selectedFolderLabel: string;
  isLoading: boolean;
  error: Error | null;
  filteredWorkflows: WorkflowSummary[];
  deletingWorkflowId: number | null;
  editingWorkflowId: number | undefined;
  isDeletePending: boolean;
  isExportPending: boolean;
  exportingWorkflowId: number | undefined;
  onDeleteConfirm: () => void;
  onDeleteCancel: () => void;
  onEdit: (workflow: WorkflowSummary) => void;
  onExport: (workflow: WorkflowSummary) => void;
  onDelete: (workflow: WorkflowSummary) => void;
}

export function WorkflowManageFilters({
  selectedFolderLabel,
  isLoading,
  error,
  filteredWorkflows,
  deletingWorkflowId,
  editingWorkflowId,
  isDeletePending,
  isExportPending,
  exportingWorkflowId,
  onDeleteConfirm,
  onDeleteCancel,
  onEdit,
  onExport,
  onDelete,
}: WorkflowManageFiltersProps) {
  return (
    <div className="flex-1 overflow-y-auto p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Workflows in{" "}
        <span className="text-primary">{selectedFolderLabel}</span>
      </p>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Failed to load workflows.</p>
      ) : filteredWorkflows.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          No workflows in this folder.
        </p>
      ) : (
        <div className="space-y-2">
          {filteredWorkflows.map((wf) =>
            deletingWorkflowId === wf.id ? (
              <DeleteConfirmRow
                key={wf.id}
                name={wf.name}
                isDeleting={isDeletePending}
                onConfirm={onDeleteConfirm}
                onCancel={onDeleteCancel}
              />
            ) : (
              <WorkflowRow
                key={wf.id}
                workflow={wf}
                isEditing={editingWorkflowId === wf.id}
                isExporting={isExportPending && exportingWorkflowId === wf.id}
                onEdit={() => onEdit(wf)}
                onExport={() => onExport(wf)}
                onDelete={() => onDelete(wf)}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}
