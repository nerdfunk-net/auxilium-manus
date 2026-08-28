"use client";

import { Download, FileText, GitBranch, Loader2, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { WorkflowSummary } from "../types/workflow-persistence";
import { getFolderLabel } from "../utils/workflow-folders";

interface WorkflowRowProps {
  workflow: WorkflowSummary;
  isEditing: boolean;
  isExporting: boolean;
  onEdit: () => void;
  onExport: () => void;
  onDelete: () => void;
}

export function WorkflowRow({
  workflow,
  isEditing,
  isExporting,
  onEdit,
  onExport,
  onDelete,
}: WorkflowRowProps) {
  return (
    <div
      className={cn(
        "flex items-center rounded-lg border p-4 transition-colors",
        isEditing && "border-primary/40 bg-primary/5",
      )}
    >
      <FileText className="mr-3 size-5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{workflow.name}</span>
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {getFolderLabel(workflow.folder)}
          </span>
          {workflow.is_version_controlled ? (
            <Badge variant="outline" className="gap-1 text-xs">
              <GitBranch className="size-3" />
              Versioned
            </Badge>
          ) : null}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {workflow.creator_username ?? "—"} ·{" "}
          {new Date(workflow.updated_at).toLocaleDateString()}
        </p>
      </div>
      <div className="ml-4 flex shrink-0 items-center gap-3">
        <button
          type="button"
          aria-label="Export workflow"
          className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          onClick={onExport}
          disabled={isExporting}
        >
          {isExporting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Download className="size-4" />
          )}
        </button>
        <button
          type="button"
          aria-label="Edit workflow"
          className="text-muted-foreground transition-colors hover:text-foreground"
          onClick={onEdit}
        >
          <Pencil className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Delete workflow"
          className="text-muted-foreground transition-colors hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="size-4" />
        </button>
      </div>
    </div>
  );
}

interface DeleteConfirmRowProps {
  name: string;
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function DeleteConfirmRow({
  name,
  isDeleting,
  onConfirm,
  onCancel,
}: DeleteConfirmRowProps) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-destructive/30 bg-destructive/5 p-4">
      <p className="text-sm">
        Delete <span className="font-medium">&ldquo;{name}&rdquo;</span>? This
        cannot be undone.
      </p>
      <div className="ml-4 flex shrink-0 gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={onCancel}
          disabled={isDeleting}
        >
          Cancel
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={onConfirm}
          disabled={isDeleting}
        >
          {isDeleting ? "Deleting…" : "Delete"}
        </Button>
      </div>
    </div>
  );
}
