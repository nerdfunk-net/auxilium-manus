"use client";

import { useMemo } from "react";

import { useCanvasGroups } from "./use-canvas-groups";
import { useCanvasLayout } from "./use-canvas-layout";
import { useCanvasSteps } from "./use-canvas-steps";
import { useWorkflowCanvasCore } from "./use-workflow-canvas-core";

export type { LoadedCanvasState } from "./use-workflow-canvas-core";

/**
 * Public facade over the canvas hooks — see doc/FEATURE-GROUPING.md "Canvas
 * state architecture". Split into use-workflow-canvas-core.ts (state +
 * React Flow change handlers), use-canvas-layout.ts (edge/node styling,
 * alignment, auto-layout), use-canvas-groups.ts (group/ungroup/rename/open),
 * and use-canvas-steps.ts (add/delete/duplicate steps, node config, static
 * attributes) because one hook owning all of it made the file unreadable at
 * 900+ lines and 30+ callbacks. This file exists so no call site has to know
 * about that split — the returned field set is unchanged.
 */
export function useWorkflowCanvas() {
  const core = useWorkflowCanvasCore();
  const layout = useCanvasLayout(core);
  const groups = useCanvasGroups(core);
  const steps = useCanvasSteps(core, groups);

  return useMemo(
    () => ({
      allNodes: core.allNodes,
      allEdges: core.allEdges,
      groups: core.groups,
      staticAttributes: core.staticAttributes,
      projected: core.projected,
      initialCanvasDraft: core.initialCanvasDraft,
      mountWorkflowId: core.mountWorkflowId,
      activeGroupId: core.activeGroupId,
      applyLoadedCanvas: core.applyLoadedCanvas,
      clearCanvas: core.clearCanvas,
      handleViewportChange: core.handleViewportChange,
      handleNodesChange: core.handleNodesChange,
      handleEdgesChange: core.handleEdgesChange,
      handleConnect: core.handleConnect,
      handleEdgeStyleChange: layout.handleEdgeStyleChange,
      handleEdgeLabelChange: layout.handleEdgeLabelChange,
      handleEdgeStartLabelChange: layout.handleEdgeStartLabelChange,
      handleEdgeEndLabelChange: layout.handleEdgeEndLabelChange,
      handleEdgeLabelBoldChange: layout.handleEdgeLabelBoldChange,
      handleEdgeLabelFontSizeChange: layout.handleEdgeLabelFontSizeChange,
      handleNodeTitleChange: layout.handleNodeTitleChange,
      handleIncomeHandleSideChange: layout.handleIncomeHandleSideChange,
      handleOutcomeHandleSideChange: layout.handleOutcomeHandleSideChange,
      handleAlignNodes: layout.handleAlignNodes,
      handleAutoLayout: layout.handleAutoLayout,
      isAutoLayoutRunning: layout.isAutoLayoutRunning,
      handleNodeConfigChange: steps.handleNodeConfigChange,
      handleAddStep: steps.handleAddStep,
      handleAddStepAtPosition: steps.handleAddStepAtPosition,
      handleDeleteNodes: steps.handleDeleteNodes,
      handleDeleteEdge: steps.handleDeleteEdge,
      handleDuplicateNode: steps.handleDuplicateNode,
      handleGroupSelectedSteps: groups.handleGroupSelectedSteps,
      handleRenameGroup: groups.handleRenameGroup,
      handleUngroupGroup: groups.handleUngroupGroup,
      handleOpenGroup: groups.handleOpenGroup,
      handleStaticAttributesChange: steps.handleStaticAttributesChange,
    }),
    [core, layout, groups, steps],
  );
}

export type UseWorkflowCanvasResult = ReturnType<typeof useWorkflowCanvas>;
