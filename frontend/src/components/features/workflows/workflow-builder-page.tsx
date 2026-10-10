"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import type {
  AssistantContext,
  WorkflowProposal,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { canvasFingerprint } from "@/components/features/ai-assistant/utils/canvas-fingerprint";
import { useWorkflowStepsQuery } from "@/hooks/queries/use-workflow-steps-query";
import { Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { AiSessionUpdateBanner } from "./components/ai-session-update-banner";
import { CanvasErrorBoundary } from "./components/canvas-error-boundary";
import { CanvasGroupBreadcrumb } from "./components/canvas-group-breadcrumb";
import { NodeConfigModal } from "./components/node-config-modal";
import { WorkflowCanvas } from "./components/workflow-canvas";
import { WorkflowPropertiesPanel } from "./components/workflow-properties-panel";
import { WorkflowRunControls } from "./components/workflow-run-controls";
import { WorkflowTopbar } from "./components/workflow-topbar";
import { EMPTY_PLUGINS } from "./constants/empty-canvas";
import { StepLibraryDialog } from "./dialogs/step-library-dialog";
import { GroupConnectionDialog } from "./dialogs/group-connection-dialog";
import { WorkflowHistoryDialog } from "./dialogs/workflow-history-dialog";
import { WorkflowManageDialog } from "./dialogs/workflow-manage-dialog";
import { WorkflowOpenDialog } from "./dialogs/workflow-open-dialog";
import { WorkflowRunInputsDialog } from "./dialogs/workflow-run-inputs-dialog";
import { WorkflowSaveAsDialog } from "./dialogs/workflow-save-as-dialog";
import { WorkflowValidationDialog } from "./dialogs/workflow-validation-dialog";
import { WorkflowWikiDialog } from "./dialogs/workflow-wiki-dialog";
import type { StaticAttributeDef } from "./types/workflow-persistence";
import { canvasFromWorkflowResponse } from "./utils/apply-loaded-workflow";
import { canvasPersistPayload } from "./utils/canvas-persist-payload";
import { isGroupCanvasNode } from "./utils/canvas-group-projection";
import { computeDeviceParamConfigs } from "./utils/device-param-hints";
import { useUnsavedChangesWarning } from "./hooks/use-unsaved-changes-warning";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";
import { useWorkflowCanvas } from "./hooks/use-workflow-canvas";
import { useWorkflowKeyboardShortcuts } from "./hooks/use-workflow-keyboard-shortcuts";
import { useWorkflowPersistence } from "./hooks/use-workflow-persistence";
import { useWorkflowRunActions } from "./hooks/use-workflow-run-actions";
import { useWorkflowValidation } from "./hooks/use-workflow-validation";

export function WorkflowBuilderPage() {
  const resetToNew = useWorkflowBuilderStore((state) => state.resetToNew);
  const openStepLibrary = useWorkflowBuilderStore(
    (state) => state.openStepLibrary,
  );
  const closeStepLibrary = useWorkflowBuilderStore(
    (state) => state.closeStepLibrary,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const autoLayoutDirection = useWorkflowBuilderStore(
    (state) => state.autoLayoutDirection,
  );
  const setAutoLayoutDirection = useWorkflowBuilderStore(
    (state) => state.setAutoLayoutDirection,
  );
  useUnsavedChangesWarning(isDirty);
  // The store outlives this page; never reopen the library on the next visit.
  useEffect(() => closeStepLibrary, [closeStepLibrary]);
  const {
    data: pluginResponse,
    error: pluginError,
    isLoading: isPluginsLoading,
  } = useWorkflowStepsQuery();
  const plugins = pluginResponse?.plugins ?? EMPTY_PLUGINS;

  const requestRunRef = useRef<(id: number) => void>(() => {});
  const canvas = useWorkflowCanvas();
  const moveTargetGroups = useMemo(
    () => canvas.groups.map((group) => ({ id: group.id, title: group.title })),
    [canvas.groups],
  );
  const deviceParamConfigs = useMemo(
    () => computeDeviceParamConfigs(canvas.allNodes),
    [canvas.allNodes],
  );
  // The config modal needs both every real node (so a validation-dialog click on a
  // node currently hidden inside a collapsed group can still open it) and the
  // synthetic group nodes (only present in the current projection, never in
  // allNodes) so a Group's own "Open configuration" can resolve too.
  const nodesForConfigModal = useMemo(
    () => [
      ...canvas.allNodes,
      ...canvas.projected.nodes.filter(isGroupCanvasNode),
    ],
    [canvas.allNodes, canvas.projected.nodes],
  );
  const persistence = useWorkflowPersistence({
    canvas,
    plugins,
    isPluginsLoading,
    requestRunRef,
  });
  const run = useWorkflowRunActions({ canvas, persistence });
  const validation = useWorkflowValidation({
    workflowId: persistence.workflowId,
    allNodes: canvas.allNodes,
    allEdges: canvas.allEdges,
  });
  const markDirty = useWorkflowBuilderStore((state) => state.markDirty);

  // --- AI assistant (rendered only while the user has it enabled) ---------------------------
  const assistantAvailable = useAiAssistantAvailable();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const toggleAssistant = useCallback(
    () => setAssistantOpen((open) => !open),
    [],
  );
  const { allNodes, allEdges, groups, staticAttributes, applyLoadedCanvas } =
    canvas;
  const workflowNameForAssistant = persistence.workflowName;
  const getAssistantContext = useCallback((): AssistantContext => {
    const payload = canvasPersistPayload(
      allNodes,
      allEdges,
      groups,
      staticAttributes,
    );
    return {
      surface: "workflow_editor",
      name: workflowNameForAssistant,
      ...payload,
      static_attributes: payload.static_attributes as unknown as Record<
        string,
        unknown
      >[],
    };
  }, [allNodes, allEdges, groups, staticAttributes, workflowNameForAssistant]);
  const applyWorkflowProposal = useCallback(
    (proposal: WorkflowProposal) => {
      // Same path as loading a saved workflow, so the canvas migrates/repairs it identically; the
      // result stays unsaved until the user saves.
      applyLoadedCanvas(
        canvasFromWorkflowResponse(
          {
            canvas_nodes: proposal.canvas_nodes,
            canvas_edges: proposal.canvas_edges,
            canvas_groups: proposal.canvas_groups,
            static_attributes:
              proposal.static_attributes as unknown as StaticAttributeDef[],
          },
          plugins,
        ),
      );
      markDirty();
    },
    [applyLoadedCanvas, markDirty, plugins],
  );
  const workflowTarget = useMemo(
    () => ({
      currentFingerprint: canvasFingerprint(
        allNodes as unknown as Record<string, unknown>[],
        allEdges as unknown as Record<string, unknown>[],
      ),
      onApply: applyWorkflowProposal,
    }),
    [allNodes, allEdges, applyWorkflowProposal],
  );

  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const openConfigModal = useWorkflowBuilderStore(
    (state) => state.openConfigModal,
  );
  const { requestRun } = run;
  useEffect(() => {
    requestRunRef.current = (id) => {
      void requestRun(id);
    };
  }, [requestRun]);

  const { handleSave, handleOpen, setIsSaveAsOpen } = persistence;
  const handleSaveAsShortcut = useCallback(() => {
    setIsSaveAsOpen(true);
  }, [setIsSaveAsOpen]);
  useWorkflowKeyboardShortcuts({
    onSave: handleSave,
    onSaveAs: handleSaveAsShortcut,
    onOpen: handleOpen,
  });

  // Cross-route "Load Workflow" / "Show Run" requests (Schedules page). The
  // caller only sets `pendingWorkflowLoad` + navigates here; we run the normal
  // full load, then hand off to /workflows/runs if `thenRuns` was asked.
  const router = useRouter();
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const pendingWorkflowLoad = useWorkflowBuilderStore(
    (state) => state.pendingWorkflowLoad,
  );
  const clearPendingWorkflowLoad = useWorkflowBuilderStore(
    (state) => state.clearPendingWorkflowLoad,
  );
  const { handleLoadWorkflow } = persistence;
  // Ref (not state): the handoff is driven by the store `workflowId` changing,
  // so it needs no re-render of its own.
  const awaitingRunsHandoffRef = useRef<number | null>(null);

  useEffect(() => {
    if (!pendingWorkflowLoad || isPluginsLoading) return;
    const { workflowId: pendingId, thenRuns } = pendingWorkflowLoad;
    clearPendingWorkflowLoad();
    awaitingRunsHandoffRef.current = thenRuns ? pendingId : null;
    handleLoadWorkflow({ id: pendingId });
  }, [
    pendingWorkflowLoad,
    isPluginsLoading,
    clearPendingWorkflowLoad,
    handleLoadWorkflow,
  ]);

  useEffect(() => {
    // The load has landed (store metadata now reflects the target) — safe to
    // leave the builder for the runs view without racing the canvas apply.
    const target = awaitingRunsHandoffRef.current;
    if (target == null || workflowId !== target) return;
    awaitingRunsHandoffRef.current = null;
    router.replace("/workflows/runs");
  }, [workflowId, router]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <WorkflowTopbar
        onNew={persistence.handleNew}
        onOpen={persistence.handleOpen}
        onManage={() => persistence.setIsManageOpen(true)}
        onRun={run.handleRun}
        onSave={persistence.handleSave}
        onSaveAs={() => persistence.setIsSaveAsOpen(true)}
        onVersionControl={() => persistence.setIsHistoryOpen(true)}
        onValidate={validation.handleValidate}
        isValidating={validation.isValidating}
        onToggleAssistant={assistantAvailable ? toggleAssistant : undefined}
        isAssistantOpen={assistantOpen}
      />
      <main className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <CanvasGroupBreadcrumb groups={canvas.groups} />
          <AiSessionUpdateBanner
            workflowId={persistence.workflowId}
            baselineUpdatedAt={persistence.baselineUpdatedAt}
            onReload={() => {
              if (persistence.workflowId != null) {
                persistence.handleLoadWorkflow({ id: persistence.workflowId });
              }
            }}
          />
          <div className="min-h-0 flex-1">
            <CanvasErrorBoundary onReset={resetToNew}>
              <WorkflowCanvas
                edges={canvas.projected.edges}
                nodes={canvas.projected.nodes}
                onEdgesChange={canvas.handleEdgesChange}
                onNodesChange={canvas.handleNodesChange}
                onConnect={canvas.handleConnect}
                onRequestStepLibrary={openStepLibrary}
                outcomeProvides={canvas.outcomeProvides}
                getGroupConnectionEnds={canvas.getGroupConnectionEnds}
                isInsideGroup={canvas.activeGroupId !== null}
                onMoveNodesToGroup={canvas.handleMoveToGroup}
                onMoveNodesOutOfGroup={canvas.handleMoveOutOfGroup}
                initialViewport={canvas.initialCanvasDraft?.viewport}
                onViewportChange={canvas.handleViewportChange}
                validationByNodeId={validation.validationByNodeId}
              />
            </CanvasErrorBoundary>
          </div>
        </section>
        {assistantAvailable && assistantOpen ? (
          <aside
            className="flex w-[420px] shrink-0 flex-col gap-3 border-l bg-card p-4"
            aria-label="AI Assistant"
          >
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Sparkles className="size-4" />
                AI Assistant
              </h2>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => setAssistantOpen(false)}
                aria-label="Close assistant"
              >
                <X className="size-4" />
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <AssistantPanel
                placeholder="Describe the workflow you need, or what to change…"
                getContext={getAssistantContext}
                workflowTarget={workflowTarget}
              />
            </div>
          </aside>
        ) : null}
        <WorkflowPropertiesPanel
          edges={canvas.projected.edges}
          nodes={canvas.projected.nodes}
          onAlignNodes={canvas.handleAlignNodes}
          autoLayoutDirection={autoLayoutDirection}
          isAutoLayoutRunning={canvas.isAutoLayoutRunning}
          onAutoLayoutDirectionChange={setAutoLayoutDirection}
          onAutoLayoutNodes={(nodeIds) =>
            canvas.handleAutoLayout(nodeIds, autoLayoutDirection)
          }
          onDeleteEdge={canvas.handleDeleteEdge}
          onDeleteNodes={canvas.handleDeleteNodes}
          onDuplicateNode={canvas.handleDuplicateNode}
          onEdgeEndLabelChange={canvas.handleEdgeEndLabelChange}
          onEdgeLabelBoldChange={canvas.handleEdgeLabelBoldChange}
          onEdgeLabelChange={canvas.handleEdgeLabelChange}
          onEdgeLabelFontSizeChange={canvas.handleEdgeLabelFontSizeChange}
          onEdgeStartLabelChange={canvas.handleEdgeStartLabelChange}
          onEdgeStyleChange={canvas.handleEdgeStyleChange}
          onGroupSelectedSteps={canvas.handleGroupSelectedSteps}
          onNodeTitleChange={canvas.handleNodeTitleChange}
          onNodeDisabledChange={canvas.handleNodeDisabledChange}
          onNodesDisabledChange={canvas.handleNodesDisabledChange}
          onOpenGroup={canvas.handleOpenGroup}
          onRenameGroup={canvas.handleRenameGroup}
          onUngroupGroup={canvas.handleUngroupGroup}
          isInsideGroup={canvas.activeGroupId !== null}
          groups={moveTargetGroups}
          onMoveToGroup={canvas.handleMoveToGroup}
          onMoveOutOfGroup={canvas.handleMoveOutOfGroup}
          staticAttributes={canvas.staticAttributes}
          onStaticAttributesChange={canvas.handleStaticAttributesChange}
        />
        <NodeConfigModal
          nodes={nodesForConfigModal}
          edges={canvas.allEdges}
          plugins={plugins}
          onNodeConfigChange={canvas.handleNodeConfigChange}
          onNodeTitleChange={canvas.handleNodeTitleChange}
          onNodeDisabledChange={canvas.handleNodeDisabledChange}
          onNodeIncomeHandleSideChange={canvas.handleIncomeHandleSideChange}
          onNodeOutcomeHandleSideChange={canvas.handleOutcomeHandleSideChange}
          onRenameGroup={canvas.handleRenameGroup}
          workflowNodes={canvas.allNodes}
        />
      </main>
      <StepLibraryDialog
        errorMessage={pluginError?.message}
        isLoading={isPluginsLoading}
        onAddStep={canvas.handleAddStep}
        onAddStepAtPosition={canvas.handleAddStepAtPosition}
        plugins={plugins}
      />
      <GroupConnectionDialog
        pending={canvas.pendingGroupConnection}
        onResolve={canvas.resolvePendingGroupConnection}
      />
      <WorkflowRunControls
        isAutoLayoutRunning={canvas.isAutoLayoutRunning}
        onAutoLayout={() => canvas.handleAutoLayout(null, autoLayoutDirection)}
        onOpenWiki={() => persistence.setIsWikiOpen(true)}
      />

      <WorkflowSaveAsDialog
        open={persistence.isSaveAsOpen}
        defaultName={persistence.workflowName}
        defaultDescription={persistence.workflowDescription}
        defaultFolder={persistence.workflowFolder}
        defaultVisibility={persistence.workflowVisibility}
        defaultIsVersionControlled={persistence.workflowIsVersionControlled}
        isSaving={
          persistence.createWorkflow.isPending ||
          persistence.updateWorkflow.isPending
        }
        onSave={persistence.handleSaveAs}
        onOverwrite={persistence.handleOverwrite}
        onClose={persistence.closeSaveAs}
      />

      <WorkflowOpenDialog
        open={persistence.isOpenDialogOpen}
        onOpen={persistence.handleLoadWorkflow}
        onClose={() => persistence.setIsOpenDialogOpen(false)}
      />

      <WorkflowManageDialog
        open={persistence.isManageOpen}
        onClose={() => persistence.setIsManageOpen(false)}
      />

      <WorkflowHistoryDialog
        open={persistence.isHistoryOpen}
        workflowId={persistence.workflowId}
        workflowName={persistence.workflowName}
        onClose={() => persistence.setIsHistoryOpen(false)}
        onRestored={persistence.handleRestored}
      />

      <WorkflowWikiDialog
        open={persistence.isWikiOpen}
        workflowId={persistence.workflowId}
        workflowName={persistence.workflowName}
        onClose={() => persistence.setIsWikiOpen(false)}
      />

      <WorkflowValidationDialog
        open={validation.isDialogOpen}
        onOpenChange={validation.setIsDialogOpen}
        result={validation.result}
        allNodes={canvas.allNodes}
        onSelectNode={(nodeId) => {
          selectNode(nodeId);
          openConfigModal(nodeId);
          validation.setIsDialogOpen(false);
        }}
      />

      <Dialog
        open={persistence.isNewConfirmOpen}
        onOpenChange={(open) => !open && persistence.setIsNewConfirmOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Discard unsaved changes?</DialogTitle>
            <DialogDescription>
              The current workflow has unsaved changes. Creating a new workflow
              will discard them permanently.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => persistence.setIsNewConfirmOpen(false)}
            >
              Keep editing
            </Button>
            <Button variant="destructive" onClick={persistence.confirmNew}>
              Discard &amp; create new
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={persistence.isOpenConfirmOpen}
        onOpenChange={(open) =>
          !open && persistence.setIsOpenConfirmOpen(false)
        }
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Unsaved changes</DialogTitle>
            <DialogDescription>
              The current workflow has unsaved changes. Save before opening
              another workflow?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button
              variant="outline"
              onClick={() => persistence.setIsOpenConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="outline"
              onClick={persistence.handleDiscardAndOpen}
            >
              Discard &amp; open
            </Button>
            <Button
              onClick={persistence.handleSaveAndOpen}
              disabled={persistence.updateWorkflow.isPending}
            >
              {persistence.updateWorkflow.isPending ? "Saving…" : "Save & open"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={run.isRunConfirmOpen}
        onOpenChange={(open) => !open && run.setIsRunConfirmOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Unsaved changes</DialogTitle>
            <DialogDescription>
              {persistence.workflowId
                ? "The current workflow has unsaved changes. Save before running?"
                : "This workflow has not been saved yet. Save before running?"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col gap-2 sm:flex-row">
            <Button
              variant="outline"
              onClick={() => run.setIsRunConfirmOpen(false)}
            >
              Cancel
            </Button>
            {persistence.workflowId ? (
              <Button variant="outline" onClick={run.handleRunSavedVersion}>
                Run saved version
              </Button>
            ) : null}
            <Button
              onClick={run.handleSaveAndRun}
              disabled={
                persistence.updateWorkflow.isPending ||
                persistence.createWorkflow.isPending
              }
            >
              {persistence.updateWorkflow.isPending ||
              persistence.createWorkflow.isPending
                ? "Saving…"
                : "Save & run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WorkflowRunInputsDialog
        open={run.isRunInputsDialogOpen}
        staticAttributes={run.runInputAttributes}
        deviceParamConfigs={deviceParamConfigs}
        isSubmitting={run.triggerRun.isPending}
        onOpenChange={run.setIsRunInputsDialogOpen}
        onSubmit={run.handleRunInputsSubmit}
      />
    </div>
  );
}
