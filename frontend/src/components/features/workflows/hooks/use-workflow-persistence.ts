"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { MutableRefObject } from "react";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { PluginDefinition } from "../types/plugin-registry";
import type {
  WorkflowResponse,
  WorkflowSummary,
  WorkflowVisibility,
} from "../types/workflow-persistence";
import { canvasFromWorkflowResponse } from "../utils/apply-loaded-workflow";
import { canvasPersistPayload } from "../utils/canvas-persist-payload";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";
import { useWorkflowSave } from "./use-workflow-save";

export interface UseWorkflowPersistenceOptions {
  canvas: UseWorkflowCanvasResult;
  plugins: PluginDefinition[];
  isPluginsLoading: boolean;
  requestRunRef: MutableRefObject<(id: number) => void>;
}

export function useWorkflowPersistence({
  canvas,
  plugins,
  isPluginsLoading,
  requestRunRef,
}: UseWorkflowPersistenceOptions) {
  const {
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    applyLoadedCanvas,
    clearCanvas,
    mountWorkflowId,
    initialCanvasDraft,
  } = canvas;

  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowDescription = useWorkflowBuilderStore(
    (state) => state.workflowDescription,
  );
  const workflowFolder = useWorkflowBuilderStore(
    (state) => state.workflowFolder,
  );
  const workflowVisibility = useWorkflowBuilderStore(
    (state) => state.workflowVisibility,
  );
  const workflowIsVersionControlled = useWorkflowBuilderStore(
    (state) => state.workflowIsVersionControlled,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const markSaved = useWorkflowBuilderStore((state) => state.markSaved);
  const markDirty = useWorkflowBuilderStore((state) => state.markDirty);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const loadWorkflow = useWorkflowBuilderStore((state) => state.loadWorkflow);
  const resetToNew = useWorkflowBuilderStore((state) => state.resetToNew);

  const [isSaveAsOpen, setIsSaveAsOpen] = useState(false);
  const [isOpenDialogOpen, setIsOpenDialogOpen] = useState(false);
  const [isOpenConfirmOpen, setIsOpenConfirmOpen] = useState(false);
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isWikiOpen, setIsWikiOpen] = useState(false);
  const [isNewConfirmOpen, setIsNewConfirmOpen] = useState(false);
  const [openAfterSave, setOpenAfterSave] = useState(false);
  const [runAfterSave, setRunAfterSave] = useState(false);

  const { apiCall } = useApi();

  const canvasPayload = useMemo(
    () => canvasPersistPayload(allNodes, allEdges, groups, staticAttributes),
    [allNodes, allEdges, groups, staticAttributes],
  );

  const {
    handleSave,
    handleSaveAs,
    handleOverwrite,
    handleSaveAndOpen,
    createWorkflow,
    updateWorkflow,
  } = useWorkflowSave({
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
  });

  const rehydrateCanvasQuery = useQuery({
    queryKey: queryKeys.workflows.detail(mountWorkflowId ?? 0),
    queryFn: () => apiCall<WorkflowResponse>(`workflows/${mountWorkflowId}`),
    enabled: initialCanvasDraft === null && mountWorkflowId != null && !isPluginsLoading,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });

  useEffect(() => {
    if (!rehydrateCanvasQuery.data) return;
    const loaded = canvasFromWorkflowResponse(rehydrateCanvasQuery.data, plugins);
    applyLoadedCanvas(loaded);
    if (loaded.migrated) markDirty();
  }, [rehydrateCanvasQuery.data, plugins, applyLoadedCanvas, markDirty]);

  useEffect(() => {
    if (!rehydrateCanvasQuery.error) return;
    markError("Failed to restore workflow canvas");
  }, [rehydrateCanvasQuery.error, markError]);

  const confirmNew = useCallback(() => {
    resetToNew();
    clearCanvas();
    setIsNewConfirmOpen(false);
  }, [resetToNew, clearCanvas]);

  const handleNew = useCallback(() => {
    if (isDirty) {
      setIsNewConfirmOpen(true);
    } else {
      confirmNew();
    }
  }, [isDirty, confirmNew]);

  const handleOpen = useCallback(() => {
    if (isDirty) {
      setIsOpenConfirmOpen(true);
    } else {
      setIsOpenDialogOpen(true);
    }
  }, [isDirty]);

  const handleSaveAndOpenWithConfirm = useCallback(async () => {
    setIsOpenConfirmOpen(false);
    await handleSaveAndOpen();
  }, [handleSaveAndOpen]);

  const handleDiscardAndOpen = useCallback(() => {
    setIsOpenConfirmOpen(false);
    setIsOpenDialogOpen(true);
  }, []);

  const handleLoadWorkflow = useCallback(
    (summary: Pick<WorkflowSummary, "id">) => {
      apiCall<WorkflowResponse>(`workflows/${summary.id}`)
        .then((full) => {
          const loaded = canvasFromWorkflowResponse(full, plugins);
          applyLoadedCanvas(loaded);
          loadWorkflow({
            workflowId: full.id,
            workflowUuid: full.uuid ?? null,
            workflowName: full.name,
            workflowDescription: full.description ?? "",
            workflowFolder: full.folder ?? "/",
            workflowVisibility: full.visibility as WorkflowVisibility,
            workflowIsVersionControlled: full.is_version_controlled,
            workflowNotes: full.notes ?? null,
          });
          if (loaded.migrated) {
            markDirty();
          }
        })
        .catch(() => markError("Failed to load workflow"));
    },
    [apiCall, loadWorkflow, markError, markDirty, plugins, applyLoadedCanvas],
  );

  const handleRestored = useCallback(
    (full: WorkflowResponse) => {
      const loaded = canvasFromWorkflowResponse(full, plugins);
      applyLoadedCanvas(loaded);
      loadWorkflow({
        workflowId: full.id,
        workflowUuid: full.uuid ?? null,
        workflowName: full.name,
        workflowDescription: full.description ?? "",
        workflowFolder: full.folder ?? "/",
        workflowVisibility: full.visibility as WorkflowVisibility,
        workflowIsVersionControlled: full.is_version_controlled,
        workflowNotes: full.notes ?? null,
      });
      markSaved(`Restored "${full.name}"`);
    },
    [applyLoadedCanvas, loadWorkflow, markSaved, plugins],
  );

  const beginSaveAsThenRun = useCallback(() => {
    setRunAfterSave(true);
    setIsSaveAsOpen(true);
  }, []);

  const closeSaveAs = useCallback(() => {
    setIsSaveAsOpen(false);
    setOpenAfterSave(false);
    setRunAfterSave(false);
  }, []);

  return useMemo(
    () => ({
      isSaveAsOpen,
      isOpenDialogOpen,
      isOpenConfirmOpen,
      isManageOpen,
      isHistoryOpen,
      isWikiOpen,
      isNewConfirmOpen,
      openAfterSave,
      runAfterSave,
      setIsSaveAsOpen,
      setIsOpenDialogOpen,
      setIsOpenConfirmOpen,
      setIsManageOpen,
      setIsHistoryOpen,
      setIsWikiOpen,
      setIsNewConfirmOpen,
      closeSaveAs,
      confirmNew,
      handleNew,
      handleSave,
      handleSaveAs,
      handleOverwrite,
      handleOpen,
      handleSaveAndOpen: handleSaveAndOpenWithConfirm,
      handleDiscardAndOpen,
      handleLoadWorkflow,
      handleRestored,
      beginSaveAsThenRun,
      createWorkflow,
      updateWorkflow,
      workflowId,
      workflowName,
      workflowDescription,
      workflowFolder,
      workflowVisibility,
      workflowIsVersionControlled,
    }),
    [
      isSaveAsOpen,
      isOpenDialogOpen,
      isOpenConfirmOpen,
      isManageOpen,
      isHistoryOpen,
      isWikiOpen,
      isNewConfirmOpen,
      openAfterSave,
      runAfterSave,
      closeSaveAs,
      confirmNew,
      handleNew,
      handleSave,
      handleSaveAs,
      handleOverwrite,
      handleOpen,
      handleSaveAndOpenWithConfirm,
      handleDiscardAndOpen,
      handleLoadWorkflow,
      handleRestored,
      beginSaveAsThenRun,
      createWorkflow,
      updateWorkflow,
      workflowId,
      workflowName,
      workflowDescription,
      workflowFolder,
      workflowVisibility,
      workflowIsVersionControlled,
    ],
  );
}

export type UseWorkflowPersistenceResult = ReturnType<typeof useWorkflowPersistence>;
