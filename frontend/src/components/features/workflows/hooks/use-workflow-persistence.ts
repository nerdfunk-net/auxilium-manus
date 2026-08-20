"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { MutableRefObject } from "react";

import { useWorkflowMutations } from "@/hooks/queries/use-workflow-mutations";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { PluginDefinition } from "../types/plugin-registry";
import type {
  WorkflowResponse,
  WorkflowSummary,
  WorkflowVisibility,
} from "../types/workflow-persistence";
import { canvasFromWorkflowResponse } from "../utils/apply-loaded-workflow";
import { validateCanvasWorkflow } from "../utils/workflow-validation";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

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
  const [isNewConfirmOpen, setIsNewConfirmOpen] = useState(false);
  // When the user chooses "Save & Open" but has no workflowId, Save As runs first.
  // This flag tells handleSaveAs to open the Open dialog once saving completes.
  const [openAfterSave, setOpenAfterSave] = useState(false);
  // When the user chooses "Save & Run" but has no workflowId, Save As runs first.
  const [runAfterSave, setRunAfterSave] = useState(false);

  const { createWorkflow, updateWorkflow } = useWorkflowMutations();
  const { apiCall } = useApi();

  // Fallback for when no matching draft was found above (true first mount of
  // the editor in this browser session with a workflow already recorded in
  // the store, or the store's draft belongs to a different workflow): fetch
  // the last saved canvas from the backend so it isn't shown blank.
  // This is a one-shot rehydration fetch, not a live-syncing query: it should
  // run once when a mount without a local draft becomes ready, then never
  // refetch (no window-focus refetch, no auto-retry).
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
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
          static_attributes: staticAttributes,
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
      createWorkflow,
      loadWorkflow,
      markSaved,
      markError,
      openAfterSave,
      runAfterSave,
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
            canvas_nodes: allNodes as unknown as Record<string, unknown>[],
            canvas_edges: allEdges as unknown as Record<string, unknown>[],
            canvas_groups: groups as unknown as Record<string, unknown>[],
            static_attributes: staticAttributes,
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
      updateWorkflow,
      loadWorkflow,
      markSaved,
      markError,
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
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
          static_attributes: staticAttributes,
        },
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
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
  ]);

  const handleOpen = useCallback(() => {
    if (isDirty) {
      setIsOpenConfirmOpen(true);
    } else {
      setIsOpenDialogOpen(true);
    }
  }, [isDirty]);

  const handleSaveAndOpen = useCallback(async () => {
    setIsOpenConfirmOpen(false);
    if (!workflowId) {
      // No saved ID yet — delegate naming to Save As, then open when done.
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
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
          static_attributes: staticAttributes,
        },
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
    updateWorkflow,
    markSaved,
    markError,
    workflowName,
  ]);

  const handleDiscardAndOpen = useCallback(() => {
    setIsOpenConfirmOpen(false);
    setIsOpenDialogOpen(true);
  }, []);

  const handleLoadWorkflow = useCallback(
    (summary: WorkflowSummary) => {
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
          });
          if (loaded.migrated) {
            markDirty();
          }
        })
        .catch(() => markError("Failed to load workflow"));
    },
    [apiCall, loadWorkflow, markError, markDirty, plugins, applyLoadedCanvas],
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
      isNewConfirmOpen,
      openAfterSave,
      runAfterSave,
      setIsSaveAsOpen,
      setIsOpenDialogOpen,
      setIsOpenConfirmOpen,
      setIsManageOpen,
      setIsNewConfirmOpen,
      closeSaveAs,
      confirmNew,
      handleNew,
      handleSave,
      handleSaveAs,
      handleOverwrite,
      handleOpen,
      handleSaveAndOpen,
      handleDiscardAndOpen,
      handleLoadWorkflow,
      beginSaveAsThenRun,
      createWorkflow,
      updateWorkflow,
      workflowId,
      workflowName,
      workflowDescription,
      workflowFolder,
      workflowVisibility,
    }),
    [
      isSaveAsOpen,
      isOpenDialogOpen,
      isOpenConfirmOpen,
      isManageOpen,
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
      handleSaveAndOpen,
      handleDiscardAndOpen,
      handleLoadWorkflow,
      beginSaveAsThenRun,
      createWorkflow,
      updateWorkflow,
      workflowId,
      workflowName,
      workflowDescription,
      workflowFolder,
      workflowVisibility,
    ],
  );
}

export type UseWorkflowPersistenceResult = ReturnType<typeof useWorkflowPersistence>;
