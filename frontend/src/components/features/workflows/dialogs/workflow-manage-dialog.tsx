"use client";

import { useCallback, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { FileText, Pencil, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

import { WorkflowFolderSidebar } from "../components/workflow-folder-sidebar";
import type {
  WorkflowListResponse,
  WorkflowSummary,
  WorkflowVisibility,
} from "../types/workflow-persistence";
import {
  buildFolderCounts,
  getFolderLabel,
  getSortedFolders,
  normalizeFolder,
} from "../utils/workflow-folders";

const editSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  folder: z.string().max(500).optional(),
  visibility: z.enum(["public", "private"]),
});

type EditFormValues = z.infer<typeof editSchema>;

interface WorkflowManageDialogProps {
  open: boolean;
  onClose: () => void;
}

export function WorkflowManageDialog({ open, onClose }: WorkflowManageDialogProps) {
  const { data, isLoading, error } = useWorkflowsQuery();
  const { updateWorkflow, deleteWorkflow } = useWorkflowMutations();
  const queryClient = useQueryClient();

  const workflows = useMemo(() => data?.workflows ?? [], [data]);

  const folderCounts = useMemo(() => buildFolderCounts(workflows), [workflows]);
  const sortedFolders = useMemo(() => getSortedFolders(folderCounts), [folderCounts]);

  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [editingWorkflow, setEditingWorkflow] = useState<WorkflowSummary | null>(null);
  const [deletingWorkflowId, setDeletingWorkflowId] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const filteredWorkflows = useMemo(() => {
    if (selectedFolder === null) return workflows;
    return workflows.filter((wf) => normalizeFolder(wf.folder) === selectedFolder);
  }, [workflows, selectedFolder]);

  const {
    register,
    handleSubmit,
    setValue,
    control,
    reset,
    formState: { errors },
  } = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
  });

  const visibility = useWatch({ control, name: "visibility" });

  const handleEditClick = useCallback(
    (wf: WorkflowSummary) => {
      setSaveError(null);
      setSaveSuccess(null);
      setDeletingWorkflowId(null);
      setEditingWorkflow(wf);
      reset({
        name: wf.name,
        description: wf.description ?? "",
        folder: wf.folder ?? "/",
        visibility: wf.visibility,
      });
    },
    [reset],
  );

  const handleCancelEdit = useCallback(() => {
    setEditingWorkflow(null);
    setSaveError(null);
    setSaveSuccess(null);
    reset();
  }, [reset]);

  const handleSaveEdit = useCallback(
    (values: EditFormValues) => {
      if (!editingWorkflow) return;
      setSaveError(null);
      setSaveSuccess(null);
      updateWorkflow.mutate(
        { id: editingWorkflow.id, data: { ...values } },
        {
          onSuccess: (updated) => {
            // Patch the cached list immediately so the folder tree re-derives
            // without waiting for the background refetch to complete.
            queryClient.setQueryData(
              queryKeys.workflows.list(),
              (old: WorkflowListResponse | undefined) => {
                if (!old) return old;
                return {
                  ...old,
                  workflows: old.workflows.map((wf) =>
                    wf.id === updated.id
                      ? {
                          ...wf,
                          name: updated.name,
                          description: updated.description,
                          folder: updated.folder,
                          visibility: updated.visibility,
                          updated_at: updated.updated_at,
                        }
                      : wf,
                  ),
                };
              },
            );
            setSaveSuccess(`"${updated.name}" saved.`);
            setEditingWorkflow(null);
          },
          onError: () => setSaveError("Failed to update workflow."),
        },
      );
    },
    [editingWorkflow, updateWorkflow, queryClient],
  );

  const handleDeleteConfirm = useCallback(() => {
    if (deletingWorkflowId === null) return;
    deleteWorkflow.mutate(deletingWorkflowId, {
      onSuccess: () => {
        if (editingWorkflow?.id === deletingWorkflowId) {
          setEditingWorkflow(null);
          reset();
        }
        setDeletingWorkflowId(null);
      },
      onError: () => {
        setDeletingWorkflowId(null);
      },
    });
  }, [deletingWorkflowId, deleteWorkflow, editingWorkflow, reset]);

  const selectedFolderLabel =
    selectedFolder === null ? "ALL" : getFolderLabel(selectedFolder).toUpperCase();

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[88vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Manage Workflows</DialogTitle>
          <DialogDescription>View, rename, and delete your saved workflows.</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <WorkflowFolderSidebar
            totalCount={workflows.length}
            folderCounts={folderCounts}
            sortedFolders={sortedFolders}
            selectedFolder={selectedFolder}
            onSelectFolder={setSelectedFolder}
          />

          {/* Right: list + edit panel */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {/* Workflow list */}
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
                        isDeleting={deleteWorkflow.isPending}
                        onConfirm={handleDeleteConfirm}
                        onCancel={() => setDeletingWorkflowId(null)}
                      />
                    ) : (
                      <WorkflowRow
                        key={wf.id}
                        workflow={wf}
                        isEditing={editingWorkflow?.id === wf.id}
                        onEdit={() => handleEditClick(wf)}
                        onDelete={() => {
                          setDeletingWorkflowId(wf.id);
                          if (editingWorkflow?.id === wf.id) {
                            setEditingWorkflow(null);
                            reset();
                          }
                        }}
                      />
                    ),
                  )}
                </div>
              )}
            </div>

            {/* Bottom: edit panel */}
            <div className="border-t bg-muted/20 p-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                General
              </p>

              {editingWorkflow ? (
                <form
                  onSubmit={handleSubmit(handleSaveEdit)}
                  className="grid grid-cols-2 gap-3"
                >
                  <div className="grid gap-1">
                    <Label className="text-xs" htmlFor="edit-name">
                      Name
                    </Label>
                    <Input
                      id="edit-name"
                      className="h-8 text-sm"
                      {...register("name")}
                    />
                    {errors.name ? (
                      <p className="text-xs text-destructive">{errors.name.message}</p>
                    ) : null}
                  </div>

                  <div className="grid gap-1">
                    <Label className="text-xs" htmlFor="edit-folder">
                      Folder
                    </Label>
                    <Input
                      id="edit-folder"
                      className="h-8 text-sm"
                      placeholder="/"
                      {...register("folder")}
                    />
                  </div>

                  <div className="grid gap-1">
                    <Label className="text-xs" htmlFor="edit-description">
                      Description
                    </Label>
                    <Input
                      id="edit-description"
                      className="h-8 text-sm"
                      placeholder="Optional"
                      {...register("description")}
                    />
                  </div>

                  <div className="grid gap-1">
                    <Label className="text-xs" htmlFor="edit-visibility">
                      Visibility
                    </Label>
                    <Select
                      value={visibility}
                      onValueChange={(v) =>
                        setValue("visibility", v as WorkflowVisibility)
                      }
                    >
                      <SelectTrigger id="edit-visibility" className="h-8 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="private">Private</SelectItem>
                        <SelectItem value="public">Public</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {saveError ? (
                    <p className="col-span-2 text-xs text-destructive">{saveError}</p>
                  ) : null}

                  <div className="col-span-2 flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      Editing:{" "}
                      <span className="font-medium text-foreground">
                        {editingWorkflow.name}
                      </span>
                    </p>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={handleCancelEdit}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="submit"
                        size="sm"
                        disabled={updateWorkflow.isPending}
                      >
                        {updateWorkflow.isPending ? "Saving…" : "Save changes"}
                      </Button>
                    </div>
                  </div>
                </form>
              ) : (
                <p className="text-sm italic text-muted-foreground">
                  {saveSuccess ?? "Select a workflow to edit its details."}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t px-6 py-4">
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface WorkflowRowProps {
  workflow: WorkflowSummary;
  isEditing: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

function WorkflowRow({ workflow, isEditing, onEdit, onDelete }: WorkflowRowProps) {
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
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {workflow.creator_username ?? "—"} ·{" "}
          {new Date(workflow.updated_at).toLocaleDateString()}
        </p>
      </div>
      <div className="ml-4 flex shrink-0 items-center gap-3">
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

function DeleteConfirmRow({ name, isDeleting, onConfirm, onCancel }: DeleteConfirmRowProps) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-destructive/30 bg-destructive/5 p-4">
      <p className="text-sm">
        Delete{" "}
        <span className="font-medium">&ldquo;{name}&rdquo;</span>? This cannot be
        undone.
      </p>
      <div className="ml-4 flex shrink-0 gap-2">
        <Button size="sm" variant="outline" onClick={onCancel} disabled={isDeleting}>
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
