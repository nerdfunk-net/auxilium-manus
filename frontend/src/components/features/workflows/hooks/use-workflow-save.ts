"use client";

import { useCallback, useMemo } from "react";
import type { MutableRefObject } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { isConflictError } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

import type { WorkflowGitSyncStatus, WorkflowVisibility } from "../types/workflow-persistence";
import { canvasPersistPayload } from "../utils/canvas-persist-payload";
import { validateCanvasWorkflow } from "../utils/workflow-validation";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";

export interface UseWorkflowSaveOptions {
  canvas: UseWorkflowCanvasResult;
  workflowId: number | null;
  workflowName: string;
  canvasPayload: ReturnType<typeof canvasPersistPayload>;
  markSaved: (message: string) => void;
  markError: (message: string) => void;
  loadWorkflow: (values: {
    workflowId: number;
    workflowUuid: string | null;
    workflowName: string;
    workflowDescription: string;
    workflowFolder: string;
    workflowVisibility: WorkflowVisibility;
    workflowIsVersionControlled: boolean;
    workflowNotes: string | null;
  }) => void;
  setIsSaveAsOpen: (open: boolean) => void;
  openAfterSave: boolean;
  runAfterSave: boolean;
  setOpenAfterSave: (value: boolean) => void;
  setRunAfterSave: (value: boolean) => void;
  setIsOpenDialogOpen: (open: boolean) => void;
  requestRunRef: MutableRefObject<(id: number) => void>;
  /** The `updated_at` the canvas is synced to; sent as `expected_updated_at` on a plain save. */
  baselineUpdatedAtRef: MutableRefObject<string | null>;
  /** The server says the workflow changed since it was loaded (409). */
  onSaveConflict: () => void;
}

export interface SaveOptions {
  /** Skip the concurrency check (the "Overwrite" choice of the conflict dialog). */
  overwrite?: boolean;
}

function saveErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useWorkflowSave({
  canvas,
  workflowId,
  workflowName,
  canvasPayload,
  markSaved,
  markError,
  loadWorkflow,
  setIsSaveAsOpen,
  openAfterSave,
  runAfterSave,
  setOpenAfterSave,
  setRunAfterSave,
  setIsOpenDialogOpen,
  requestRunRef,
  baselineUpdatedAtRef,
  onSaveConflict,
}: UseWorkflowSaveOptions) {
  const { allNodes, allEdges, groups, staticAttributes } = canvas;
  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  // The mutation objects change with every state change; their functions do not, so the
  // callbacks below depend on those and keep their identity while a save is pending.
  const { mutateAsync: createWorkflowAsync } = createWorkflow;
  const { mutate: updateWorkflowMutate, mutateAsync: updateWorkflowAsync } = updateWorkflow;
  const { toast } = useToast();

  const warnIfGitSyncFailed = useCallback(
    (gitSync: WorkflowGitSyncStatus | null) => {
      if (gitSync?.status !== "failed") return;
      toast({
        title: "Saved, but Git sync failed",
        description: gitSync.message ?? "The workflow was saved, but committing to Git failed.",
        variant: "destructive",
      });
    },
    [toast],
  );

  const handleSaveAs = useCallback(
    async (values: {
      name: string;
      description?: string;
      folder?: string;
      visibility: WorkflowVisibility;
      is_version_controlled?: boolean;
    }) => {
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes, {
        requireSteps: false,
      });
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await createWorkflowAsync({
          name: values.name,
          description: values.description,
          folder: values.folder,
          visibility: values.visibility,
          is_version_controlled: values.is_version_controlled,
          ...canvasPayload,
        });
        loadWorkflow({
          workflowId: saved.id,
          workflowUuid: saved.uuid ?? null,
          workflowName: saved.name,
          workflowDescription: saved.description ?? "",
          workflowFolder: saved.folder ?? "/",
          workflowVisibility: saved.visibility as WorkflowVisibility,
          workflowIsVersionControlled: saved.is_version_controlled,
          workflowNotes: saved.notes ?? null,
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
        warnIfGitSyncFailed(saved.git_sync);
        if (openAfterSave) {
          setOpenAfterSave(false);
          setIsOpenDialogOpen(true);
        }
        if (runAfterSave) {
          setRunAfterSave(false);
          requestRunRef.current(saved.id);
        }
      } catch (error) {
        markError(saveErrorMessage(error, "Failed to save workflow"));
      }
    },
    [
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      canvasPayload,
      createWorkflowAsync,
      loadWorkflow,
      markSaved,
      markError,
      setIsSaveAsOpen,
      openAfterSave,
      runAfterSave,
      setOpenAfterSave,
      setRunAfterSave,
      setIsOpenDialogOpen,
      requestRunRef,
      warnIfGitSyncFailed,
    ],
  );

  const handleOverwrite = useCallback(
    async (
      values: {
        name: string;
        description?: string;
        folder?: string;
        visibility: WorkflowVisibility;
        is_version_controlled?: boolean;
      },
      existingId: number,
    ) => {
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes, {
        requireSteps: false,
      });
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await updateWorkflowAsync({
          id: existingId,
          data: {
            name: values.name,
            description: values.description,
            folder: values.folder,
            visibility: values.visibility,
            is_version_controlled: values.is_version_controlled,
            ...canvasPayload,
          },
        });
        loadWorkflow({
          workflowId: saved.id,
          workflowUuid: saved.uuid ?? null,
          workflowName: saved.name,
          workflowDescription: saved.description ?? "",
          workflowFolder: saved.folder ?? "/",
          workflowVisibility: saved.visibility as WorkflowVisibility,
          workflowIsVersionControlled: saved.is_version_controlled,
          workflowNotes: saved.notes ?? null,
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
        warnIfGitSyncFailed(saved.git_sync);
      } catch (error) {
        markError(saveErrorMessage(error, "Failed to overwrite workflow"));
      }
    },
    [
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      canvasPayload,
      updateWorkflowAsync,
      loadWorkflow,
      markSaved,
      markError,
      setIsSaveAsOpen,
      warnIfGitSyncFailed,
    ],
  );

  const handleSave = useCallback(
    (options: SaveOptions = {}) => {
      if (!workflowId) {
        setIsSaveAsOpen(true);
        return;
      }
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes, {
          requireSteps: false,
        });
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      const expected = options.overwrite ? undefined : (baselineUpdatedAtRef.current ?? undefined);
      updateWorkflowMutate(
        {
          id: workflowId,
          data: { ...canvasPayload, expected_updated_at: expected },
        },
        {
          onSuccess: (saved) => {
            markSaved(`Saved "${workflowName}"`);
            warnIfGitSyncFailed(saved.git_sync);
          },
          onError: (error) =>
            isConflictError(error)
              ? onSaveConflict()
              : markError(saveErrorMessage(error, "Failed to save workflow")),
        },
      );
    },
    [
      baselineUpdatedAtRef,
      onSaveConflict,
      workflowId,
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      canvasPayload,
      updateWorkflowMutate,
      markSaved,
      markError,
      workflowName,
      setIsSaveAsOpen,
      warnIfGitSyncFailed,
    ],
  );

  const handleSaveAndOpen = useCallback(async () => {
    if (!workflowId) {
      setOpenAfterSave(true);
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes, {
        requireSteps: false,
      });
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      const saved = await updateWorkflowAsync({
        id: workflowId,
        data: {
          ...canvasPayload,
          expected_updated_at: baselineUpdatedAtRef.current ?? undefined,
        },
      });
      markSaved(`Saved "${workflowName}"`);
      warnIfGitSyncFailed(saved.git_sync);
      setIsOpenDialogOpen(true);
    } catch (error) {
      if (isConflictError(error)) {
        onSaveConflict();
        return;
      }
      markError(saveErrorMessage(error, "Failed to save workflow"));
    }
  }, [
    baselineUpdatedAtRef,
    onSaveConflict,
    workflowId,
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    canvasPayload,
    updateWorkflowAsync,
    markSaved,
    markError,
    workflowName,
    setOpenAfterSave,
    setIsSaveAsOpen,
    setIsOpenDialogOpen,
    warnIfGitSyncFailed,
  ]);

  return useMemo(
    () => ({
      handleSave,
      handleSaveAs,
      handleOverwrite,
      handleSaveAndOpen,
      createWorkflow,
      updateWorkflow,
    }),
    [
      handleSave,
      handleSaveAs,
      handleOverwrite,
      handleSaveAndOpen,
      createWorkflow,
      updateWorkflow,
    ],
  );
}
