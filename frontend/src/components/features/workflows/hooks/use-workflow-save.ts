"use client";

import { useCallback } from "react";
import type { MutableRefObject } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";

import type { WorkflowVisibility } from "../types/workflow-persistence";
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

  const handleSaveAs = useCallback(
    async (values: {
      name: string;
      description?: string;
      folder?: string;
      visibility: WorkflowVisibility;
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
          ...canvasPayload,
        });
        loadWorkflow({
          workflowId: saved.id,
          workflowUuid: saved.uuid ?? null,
          workflowName: saved.name,
          workflowDescription: saved.description ?? "",
          workflowFolder: saved.folder ?? "/",
          workflowVisibility: saved.visibility as WorkflowVisibility,
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
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
    ],
  );

  const handleOverwrite = useCallback(
    async (
      values: {
        name: string;
        description?: string;
        folder?: string;
        visibility: WorkflowVisibility;
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
        });
        setIsSaveAsOpen(false);
        markSaved(`Saved as "${saved.name}"`);
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
        onSuccess: () => markSaved(`Saved "${workflowName}"`),
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
      await updateWorkflow.mutateAsync({
        id: workflowId,
        data: canvasPayload,
      });
      markSaved(`Saved "${workflowName}"`);
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
