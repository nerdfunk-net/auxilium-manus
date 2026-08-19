"use client";

import { useEffect, useRef } from "react";

import { useWorkflowStepsQuery } from "@/hooks/queries/use-workflow-steps-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { CanvasErrorBoundary } from "./components/canvas-error-boundary";
import { CanvasGroupBreadcrumb } from "./components/canvas-group-breadcrumb";
import { NodeConfigModal } from "./components/node-config-modal";
import { WorkflowCanvas } from "./components/workflow-canvas";
import { WorkflowPropertiesPanel } from "./components/workflow-properties-panel";
import { WorkflowRunControls } from "./components/workflow-run-controls";
import { WorkflowTopbar } from "./components/workflow-topbar";
import { EMPTY_PLUGINS } from "./constants/empty-canvas";
import { WorkflowManageDialog } from "./dialogs/workflow-manage-dialog";
import { WorkflowOpenDialog } from "./dialogs/workflow-open-dialog";
import { WorkflowRunInputsDialog } from "./dialogs/workflow-run-inputs-dialog";
import { WorkflowSaveAsDialog } from "./dialogs/workflow-save-as-dialog";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";
import { useWorkflowCanvas } from "./hooks/use-workflow-canvas";
import { useWorkflowPersistence } from "./hooks/use-workflow-persistence";
import { useWorkflowRunActions } from "./hooks/use-workflow-run-actions";

export function WorkflowBuilderPage() {
  const resetToNew = useWorkflowBuilderStore((state) => state.resetToNew);
  const autoLayoutDirection = useWorkflowBuilderStore((state) => state.autoLayoutDirection);
  const setAutoLayoutDirection = useWorkflowBuilderStore(
    (state) => state.setAutoLayoutDirection,
  );
  const {
    data: pluginResponse,
    error: pluginError,
    isLoading: isPluginsLoading,
  } = useWorkflowStepsQuery();
  const plugins = pluginResponse?.plugins ?? EMPTY_PLUGINS;

  const requestRunRef = useRef<(id: number) => void>(() => {});
  const canvas = useWorkflowCanvas();
  const persistence = useWorkflowPersistence({
    canvas,
    plugins,
    isPluginsLoading,
    requestRunRef,
  });
  const run = useWorkflowRunActions({ canvas, persistence });
  const { requestRun } = run;
  useEffect(() => {
    requestRunRef.current = (id) => {
      void requestRun(id);
    };
  }, [requestRun]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <WorkflowTopbar
        onNew={persistence.handleNew}
        onOpen={persistence.handleOpen}
        onManage={() => persistence.setIsManageOpen(true)}
        onRun={run.handleRun}
        onSave={persistence.handleSave}
        onSaveAs={() => persistence.setIsSaveAsOpen(true)}
      />
      <main className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <CanvasGroupBreadcrumb groups={canvas.groups} />
          <div className="min-h-0 flex-1">
            <CanvasErrorBoundary onReset={resetToNew}>
              <WorkflowCanvas
                edges={canvas.projected.edges}
                nodes={canvas.projected.nodes}
                onEdgesChange={canvas.handleEdgesChange}
                onNodesChange={canvas.handleNodesChange}
                onConnect={canvas.handleConnect}
                onAddStepAtPosition={canvas.handleAddStepAtPosition}
                plugins={plugins}
                initialViewport={canvas.initialCanvasDraft?.viewport}
                onViewportChange={canvas.handleViewportChange}
              />
            </CanvasErrorBoundary>
          </div>
        </section>
        <WorkflowPropertiesPanel
          edges={canvas.projected.edges}
          isPluginsLoading={isPluginsLoading}
          nodes={canvas.projected.nodes}
          onAddStep={canvas.handleAddStep}
          onAlignNodes={canvas.handleAlignNodes}
          autoLayoutDirection={autoLayoutDirection}
          isAutoLayoutRunning={canvas.isAutoLayoutRunning}
          onAutoLayoutDirectionChange={setAutoLayoutDirection}
          onAutoLayoutNodes={(nodeIds) => canvas.handleAutoLayout(nodeIds, autoLayoutDirection)}
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
          onOpenGroup={canvas.handleOpenGroup}
          onRenameGroup={canvas.handleRenameGroup}
          onUngroupGroup={canvas.handleUngroupGroup}
          pluginErrorMessage={pluginError?.message}
          plugins={plugins}
          isInsideGroup={canvas.activeGroupId !== null}
          staticAttributes={canvas.staticAttributes}
          onStaticAttributesChange={canvas.handleStaticAttributesChange}
        />
        <NodeConfigModal
          nodes={canvas.allNodes}
          edges={canvas.allEdges}
          plugins={plugins}
          onNodeConfigChange={canvas.handleNodeConfigChange}
          onNodeTitleChange={canvas.handleNodeTitleChange}
          onNodeIncomeHandleSideChange={canvas.handleIncomeHandleSideChange}
          onNodeOutcomeHandleSideChange={canvas.handleOutcomeHandleSideChange}
          workflowNodes={canvas.allNodes}
        />
      </main>
      <WorkflowRunControls
        isAutoLayoutRunning={canvas.isAutoLayoutRunning}
        onAutoLayout={() => canvas.handleAutoLayout(null, autoLayoutDirection)}
      />

      <WorkflowSaveAsDialog
        open={persistence.isSaveAsOpen}
        defaultName={persistence.workflowName}
        defaultDescription={persistence.workflowDescription}
        defaultFolder={persistence.workflowFolder}
        defaultVisibility={persistence.workflowVisibility}
        isSaving={persistence.createWorkflow.isPending || persistence.updateWorkflow.isPending}
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
        onOpenChange={(open) => !open && persistence.setIsOpenConfirmOpen(false)}
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
            <Button variant="outline" onClick={persistence.handleDiscardAndOpen}>
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
              disabled={persistence.updateWorkflow.isPending || persistence.createWorkflow.isPending}
            >
              {persistence.updateWorkflow.isPending || persistence.createWorkflow.isPending
                ? "Saving…"
                : "Save & run"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WorkflowRunInputsDialog
        open={run.isRunInputsDialogOpen}
        staticAttributes={canvas.staticAttributes}
        isSubmitting={run.triggerRun.isPending}
        onOpenChange={run.setIsRunInputsDialogOpen}
        onSubmit={run.handleRunInputsSubmit}
      />
    </div>
  );
}
