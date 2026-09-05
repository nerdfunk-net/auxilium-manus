"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { useGeneralSettingsQuery } from "@/hooks/queries/use-general-settings-query";
import { useTriggerRunMutation } from "@/hooks/queries/use-workflow-run-mutations";

import {
  mergeRunInputAttributes,
  staticAttributesEqual,
} from "../utils/run-input-attributes";
import { validateCanvasWorkflow } from "../utils/workflow-validation";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";
import type { UseWorkflowPersistenceResult } from "./use-workflow-persistence";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

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
  const { data: generalSettings } = useGeneralSettingsQuery();
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const markSaved = useWorkflowBuilderStore((state) => state.markSaved);
  const markRunning = useWorkflowBuilderStore((state) => state.markRunning);
  const markError = useWorkflowBuilderStore((state) => state.markError);
  const runMode = useWorkflowBuilderStore((state) => state.runMode);
  const setActiveRunId = useWorkflowBuilderStore((state) => state.setActiveRunId);

  const [isRunConfirmOpen, setIsRunConfirmOpen] = useState(false);
  const [isRunInputsDialogOpen, setIsRunInputsDialogOpen] = useState(false);
  const [pendingRunTargetId, setPendingRunTargetId] = useState<number | null>(null);

  const triggerRun = useTriggerRunMutation(workflowId);

  const runInputAttributes = useMemo(
    () => mergeRunInputAttributes(allNodes, staticAttributes),
    [allNodes, staticAttributes],
  );

  // Dispatches the run once a target workflow id and (if declared) the
  // static-attribute values are known. Split out of the old executeRun so a
  // workflow with declared static attributes can pause for a values dialog
  // between target resolution and dispatch — see doc/WORKFLOW-STEPS.md
  // "Static attributes".
  const dispatchRun = useCallback(
    async (targetId: number, runInputs: Record<string, string | number | boolean>) => {
      try {
        const run = await triggerRun.mutateAsync({
          device_ids: [],
          trigger_type: "manual",
          run_mode: runMode,
          workflowId: targetId,
          run_inputs: runInputs,
        });
        setActiveRunId(run.id);
        markRunning(runMode === "debug" ? "Debug run queued" : "Run queued");
        // Debug mode keeps the canvas visible so the paused-node highlight is
        // visible; normal runs jump to the executions list only when the
        // "Switch to Runs" setting (Settings → General) is enabled.
        if (runMode !== "debug" && (generalSettings?.switch_to_runs_on_start ?? true)) {
          router.push("/workflows/runs");
        }
      } catch {
        markError("Failed to trigger run");
      }
    },
    [triggerRun, runMode, setActiveRunId, markRunning, markError, router, generalSettings],
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
      } catch {
        markError("Failed to sync run parameters on the workflow");
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
    }
  }, []);

  const handleRunInputsSubmit = useCallback(
    async (values: Record<string, string | number | boolean>) => {
      if (pendingRunTargetId == null) return;
      setIsRunInputsDialogOpen(false);
      await dispatchRun(pendingRunTargetId, values);
      setPendingRunTargetId(null);
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
    handleStaticAttributesChange,
    markSaved,
    markError,
    workflowName,
    requestRun,
    beginSaveAsThenRun,
  ]);

  const handleRunSavedVersion = useCallback(() => {
    setIsRunConfirmOpen(false);
    void requestRun(workflowId ?? undefined, { skipValidation: true });
  }, [requestRun, workflowId]);

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
      triggerRun,
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
      triggerRun,
    ],
  );
}

export type UseWorkflowRunActionsResult = ReturnType<typeof useWorkflowRunActions>;
