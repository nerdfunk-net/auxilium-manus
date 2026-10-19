"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { useClientSettingsQuery } from "@/hooks/queries/use-client-settings-query";
import { useTriggerRunMutation } from "@/hooks/queries/use-workflow-run-mutations";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import type { StaticAttributeDef, WorkflowResponse } from "../types/workflow-persistence";
import type { CanvasNodeLike } from "../utils/device-param-hints";
import {
  mergeRunInputAttributes,
  staticAttributesEqual,
} from "../utils/run-input-attributes";
import { validateCanvasWorkflow } from "../utils/workflow-validation";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";
import type { UseWorkflowPersistenceResult } from "./use-workflow-persistence";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

function runActionErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export interface UseWorkflowRunActionsOptions {
  canvas: UseWorkflowCanvasResult;
  persistence: UseWorkflowPersistenceResult;
}

export function useWorkflowRunActions({
  canvas,
  persistence,
}: UseWorkflowRunActionsOptions) {
  const {
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    handleStaticAttributesChange,
  } = canvas;
  const { beginSaveAsThenRun, updateWorkflow, workflowId, workflowName } =
    persistence;

  const router = useRouter();
  const queryClient = useQueryClient();
  const { apiCall } = useApi();
  const { data: generalSettings } = useClientSettingsQuery();
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const markSaved = useWorkflowBuilderStore((state) => state.markSaved);
  const markRunning = useWorkflowBuilderStore((state) => state.markRunning);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const setActiveRunId = useWorkflowBuilderStore((state) => state.setActiveRunId);

  const [isRunConfirmOpen, setIsRunConfirmOpen] = useState(false);
  const [isRunInputsDialogOpen, setIsRunInputsDialogOpen] = useState(false);
  const [pendingRunTargetId, setPendingRunTargetId] = useState<number | null>(null);
  // Set only by "Run saved version": the inputs dialog then asks for the saved
  // workflow's parameters, not the ones derived from the (dirty) canvas.
  const [savedRunAttributes, setSavedRunAttributes] = useState<StaticAttributeDef[] | null>(
    null,
  );

  // useMutation returns a new object every render; only `mutateAsync` is stable.
  const { mutateAsync: triggerRunAsync, isPending: isTriggeringRun } =
    useTriggerRunMutation(workflowId);

  const canvasRunInputAttributes = useMemo(
    () => mergeRunInputAttributes(allNodes, staticAttributes),
    [allNodes, staticAttributes],
  );
  const runInputAttributes = savedRunAttributes ?? canvasRunInputAttributes;

  // Dispatches the run once a target workflow id and (if declared) the
  // static-attribute values are known. Split out of the old executeRun so a
  // workflow with declared static attributes can pause for a values dialog
  // between target resolution and dispatch — see doc/WORKFLOW-STEPS.md
  // "Static attributes".
  const dispatchRun = useCallback(
    async (targetId: number, runInputs: Record<string, string | number | boolean>) => {
      try {
        const run = await triggerRunAsync({
          device_ids: [],
          trigger_type: "manual",
          workflowId: targetId,
          run_inputs: runInputs,
        });
        setActiveRunId(run.id);
        markRunning("Run queued");
        if (generalSettings?.switch_to_runs_on_start ?? true) {
          router.push("/workflows/runs");
        }
      } catch (error) {
        markError(runActionErrorMessage(error, "Failed to trigger run"));
      }
    },
    [triggerRunAsync, setActiveRunId, markRunning, markError, router, generalSettings],
  );

  const ensureRunInputSchemaPersisted = useCallback(
    async (targetId: number, effectiveAttrs: typeof runInputAttributes) => {
      try {
        await updateWorkflow.mutateAsync({
          id: targetId,
          data: { static_attributes: effectiveAttrs },
        });
        if (!staticAttributesEqual(effectiveAttrs, staticAttributes)) {
          handleStaticAttributesChange(effectiveAttrs);
        }
        return true;
      } catch (error) {
        markError(runActionErrorMessage(error, "Failed to sync run parameters on the workflow"));
        return false;
      }
    },
    [
      staticAttributes,
      updateWorkflow,
      handleStaticAttributesChange,
      markError,
    ],
  );

  const requestRun = useCallback(
    async (
      overrideWorkflowId?: number,
      options?: { skipValidation?: boolean },
    ) => {
      const targetId = overrideWorkflowId ?? workflowId;
      if (!targetId) {
        markError("Save the workflow before running");
        return;
      }
      if (!options?.skipValidation) {
        const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
        if (!validation.isValid) {
          markError(`Cannot run: ${validation.issues[0]}`);
          return;
        }
      }

      const effectiveAttrs = mergeRunInputAttributes(allNodes, staticAttributes);
      if (effectiveAttrs.length === 0) {
        await dispatchRun(targetId, {});
        return;
      }

      const synced = await ensureRunInputSchemaPersisted(targetId, effectiveAttrs);
      if (!synced) {
        return;
      }

      setPendingRunTargetId(targetId);
      setIsRunInputsDialogOpen(true);
    },
    [
      workflowId,
      allNodes,
      allEdges,
      groups,
      staticAttributes,
      dispatchRun,
      markError,
      ensureRunInputSchemaPersisted,
    ],
  );

  const handleRunInputsDialogOpenChange = useCallback((open: boolean) => {
    setIsRunInputsDialogOpen(open);
    if (!open) {
      setPendingRunTargetId(null);
      setSavedRunAttributes(null);
    }
  }, []);

  const handleRunInputsSubmit = useCallback(
    async (values: Record<string, string | number | boolean>) => {
      if (pendingRunTargetId == null) return;
      setIsRunInputsDialogOpen(false);
      await dispatchRun(pendingRunTargetId, values);
      setPendingRunTargetId(null);
      setSavedRunAttributes(null);
    },
    [pendingRunTargetId, dispatchRun],
  );

  const handleRun = useCallback(() => {
    if (!workflowId || isDirty) {
      setIsRunConfirmOpen(true);
      return;
    }
    void requestRun();
  }, [workflowId, isDirty, requestRun]);

  const handleSaveAndRun = useCallback(async () => {
    setIsRunConfirmOpen(false);
    if (!workflowId) {
      beginSaveAsThenRun();
      return;
    }
    const validation = validateCanvasWorkflow(allNodes, allEdges, groups, staticAttributes);
    if (!validation.isValid) {
      markError(`Cannot save: ${validation.issues[0]}`);
      return;
    }
    try {
      const effectiveAttrs = mergeRunInputAttributes(allNodes, staticAttributes);
      await updateWorkflow.mutateAsync({
        id: workflowId,
        data: {
          canvas_nodes: allNodes as unknown as Record<string, unknown>[],
          canvas_edges: allEdges as unknown as Record<string, unknown>[],
          canvas_groups: groups as unknown as Record<string, unknown>[],
          static_attributes: effectiveAttrs,
        },
      });
      handleStaticAttributesChange(effectiveAttrs);
      markSaved(`Saved "${workflowName}"`);
      await requestRun();
    } catch (error) {
      markError(runActionErrorMessage(error, "Failed to save workflow"));
    }
  }, [
    workflowId,
    allNodes,
    allEdges,
    groups,
    staticAttributes,
    updateWorkflow,
    handleStaticAttributesChange,
    markSaved,
    markError,
    workflowName,
    requestRun,
    beginSaveAsThenRun,
  ]);

  // Runs what is stored, ignoring unsaved canvas edits: the run inputs come from
  // the saved nodes and static attributes, fetched fresh, and nothing is written
  // back to the workflow.
  const handleRunSavedVersion = useCallback(async () => {
    setIsRunConfirmOpen(false);
    if (!workflowId) {
      markError("Save the workflow before running");
      return;
    }
    let saved: WorkflowResponse;
    try {
      saved = await queryClient.fetchQuery({
        queryKey: queryKeys.workflows.detail(workflowId),
        queryFn: () => apiCall<WorkflowResponse>(`workflows/${workflowId}`),
        staleTime: 0,
      });
    } catch (error) {
      markError(runActionErrorMessage(error, "Failed to load the saved workflow"));
      return;
    }
    const attributes = mergeRunInputAttributes(
      (saved.canvas_nodes ?? []) as unknown as CanvasNodeLike[],
      saved.static_attributes ?? [],
    );
    if (attributes.length === 0) {
      await dispatchRun(workflowId, {});
      return;
    }
    setSavedRunAttributes(attributes);
    setPendingRunTargetId(workflowId);
    setIsRunInputsDialogOpen(true);
  }, [workflowId, queryClient, apiCall, markError, dispatchRun]);

  return useMemo(
    () => ({
      isRunConfirmOpen,
      setIsRunConfirmOpen,
      isRunInputsDialogOpen,
      setIsRunInputsDialogOpen: handleRunInputsDialogOpenChange,
      pendingRunTargetId,
      runInputAttributes,
      handleRun,
      handleSaveAndRun,
      handleRunSavedVersion,
      handleRunInputsSubmit,
      requestRun,
      dispatchRun,
      isTriggeringRun,
    }),
    [
      isRunConfirmOpen,
      isRunInputsDialogOpen,
      handleRunInputsDialogOpenChange,
      pendingRunTargetId,
      runInputAttributes,
      handleRun,
      handleSaveAndRun,
      handleRunSavedVersion,
      handleRunInputsSubmit,
      requestRun,
      dispatchRun,
      isTriggeringRun,
    ],
  );
}

export type UseWorkflowRunActionsResult = ReturnType<typeof useWorkflowRunActions>;
