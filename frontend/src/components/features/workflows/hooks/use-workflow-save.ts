"use client";

import { useCallback } from "react";
import type { MutableRefObject } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
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
  }) => void;
  setIsSaveAsOpen: (open: boolean) => void;
  openAfterSave: boolean;
  runAfterSave: boolean;
  setOpenAfterSave: (value: boolean) => void;
  setRunAfterSave: (value: boolean) => void;
  setIsOpenDialogOpen: (open: boolean) => void;
  requestRunRef: MutableRefObject<(id: number) => void>;
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
}: UseWorkflowSaveOptions) {
  const { allNodes, allEdges, groups, staticAttributes } = canvas;
  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
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
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await createWorkflow.mutateAsync({
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
      } catch {
        markError("Failed to save workflow");
      }
    },
    [
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      canvasPayload,
      createWorkflow,
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
      const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
      if (!validation.isValid) {
        markError(`Cannot save: ${validation.issues[0]}`);
        return;
      }
      try {
        const saved = await updateWorkflow.mutateAsync({
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
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
        warnIfGitSyncFailed(saved.git_sync);
      } catch {
        markError("Failed to overwrite workflow");
      }
    },
    [
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      canvasPayload,
      updateWorkflow,
      loadWorkflow,
      markSaved,
      markError,
      setIsSaveAsOpen,
      warnIfGitSyncFailed,
    ],
  );

  const handleSave = useCallback(() => {
    if (!workflowId) {
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    updateWorkflow.mutate(
      {
        id: workflowId,
        data: canvasPayload,
      },
      {
        onSuccess: (saved) => {
          markSaved(`Saved "${workflowName}"`);
          warnIfGitSyncFailed(saved.git_sync);
        },
        onError: () => markError("Failed to save workflow"),
      },
    );
  }, [
    workflowId,
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    canvasPayload,
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
    setIsSaveAsOpen,
    warnIfGitSyncFailed,
  ]);

  const handleSaveAndOpen = useCallback(async () => {
    if (!workflowId) {
      setOpenAfterSave(true);
      setIsSaveAsOpen(true);
      return;
    }
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      const saved = await updateWorkflow.mutateAsync({
        id: workflowId,
        data: canvasPayload,
      });
      markSaved(`Saved "${workflowName}"`);
      warnIfGitSyncFailed(saved.git_sync);
      setIsOpenDialogOpen(true);
    } catch {
      markError("Failed to save workflow");
    }
  }, [
    workflowId,
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    canvasPayload,
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
    setOpenAfterSave,
    setIsSaveAsOpen,
    setIsOpenDialogOpen,
    warnIfGitSyncFailed,
  ]);

  return {
    handleSave,
    handleSaveAs,
    handleOverwrite,
    handleSaveAndOpen,
    createWorkflow,
    updateWorkflow,
  };
}
