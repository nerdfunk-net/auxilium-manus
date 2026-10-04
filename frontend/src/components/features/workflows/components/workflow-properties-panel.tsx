"use client";

import { ChevronsRight, PanelRightOpen } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";

import { AddStepButton } from "./add-step-button";
import { MultiSelectPanel } from "./multi-select-panel";
import { SelectedEdgePanel } from "./selected-edge-panel";
import type { MoveTargetGroup } from "./move-to-group-control";
import { SelectedStepPanel } from "./selected-step-panel";
import { WorkflowAiSessionPanel } from "./workflow-ai-session-panel";
import { WorkflowBackgroundTierPanel } from "./workflow-background-tier-panel";
import { WorkflowStaticAttributesPanel } from "./workflow-static-attributes-panel";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  type EdgeStyle,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";

const EMPTY_EDGES: WorkflowCanvasEdge[] = [];
const EMPTY_MOVE_TARGETS: MoveTargetGroup[] = [];

interface WorkflowPropertiesPanelProps {
  nodes: ProjectedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  isInsideGroup?: boolean;
  groups?: MoveTargetGroup[];
  onMoveToGroup?: (nodeIds: string[], groupId: string) => void;
  onMoveOutOfGroup?: (nodeIds: string[]) => void;
  onEdgeStyleChange?: (edgeId: string, style: EdgeStyle) => void;
  onEdgeLabelChange?: (edgeId: string, label: string) => void;
  onEdgeStartLabelChange?: (edgeId: string, label: string) => void;
  onEdgeEndLabelChange?: (edgeId: string, label: string) => void;
  onEdgeLabelBoldChange?: (edgeId: string, bold: boolean) => void;
  onEdgeLabelFontSizeChange?: (edgeId: string, fontSize: number) => void;
  onAlignNodes?: (nodeIds: string[], alignment: NodeAlignment) => void;
  autoLayoutDirection: AutoLayoutDirection;
  isAutoLayoutRunning?: boolean;
  onAutoLayoutDirectionChange: (direction: AutoLayoutDirection) => void;
  onAutoLayoutNodes?: (nodeIds: string[]) => void;
  onDeleteNodes?: (nodeIds: string[]) => void;
  onDeleteEdge?: (edgeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onNodeTitleChange?: (nodeId: string, title: string) => void;
  onNodeDisabledChange?: (nodeId: string, disabled: boolean) => void;
  onNodesDisabledChange?: (nodeIds: string[], disabled: boolean) => void;
  onGroupSelectedSteps?: (nodeIds: string[]) => void;
  onRenameGroup?: (groupId: string, title: string) => void;
  onUngroupGroup?: (groupId: string) => void;
  onOpenGroup?: (groupId: string) => void;
  staticAttributes: StaticAttributeDef[];
  onStaticAttributesChange: (next: StaticAttributeDef[]) => void;
}

export function WorkflowPropertiesPanel({
  nodes,
  edges = EMPTY_EDGES,
  isInsideGroup = false,
  groups = EMPTY_MOVE_TARGETS,
  onMoveToGroup,
  onMoveOutOfGroup,
  onEdgeStyleChange,
  onEdgeLabelChange,
  onEdgeStartLabelChange,
  onEdgeEndLabelChange,
  onEdgeLabelBoldChange,
  onEdgeLabelFontSizeChange,
  onAlignNodes,
  autoLayoutDirection,
  isAutoLayoutRunning = false,
  onAutoLayoutDirectionChange,
  onAutoLayoutNodes,
  onDeleteNodes,
  onDeleteEdge,
  onDuplicateNode,
  onNodeTitleChange,
  onNodeDisabledChange,
  onNodesDisabledChange,
  onGroupSelectedSteps,
  onRenameGroup,
  onUngroupGroup,
  onOpenGroup,
  staticAttributes,
  onStaticAttributesChange,
}: WorkflowPropertiesPanelProps) {
  const selectedNodeId = useWorkflowBuilderStore((state) => state.selectedNodeId);
  const selectedEdgeId = useWorkflowBuilderStore((state) => state.selectedEdgeId);
  const openConfigModal = useWorkflowBuilderStore((state) => state.openConfigModal);
  const [isCollapsed, setIsCollapsed] = useState(false);

  const selectedCanvasNodes = useMemo(
    () => nodes.filter((node) => node.selected),
    [nodes],
  );
  const isMultiSelect = selectedCanvasNodes.length > 1;

  const singleNode = useMemo(() => {
    if (selectedCanvasNodes.length === 1) return selectedCanvasNodes[0];
    if (selectedCanvasNodes.length === 0 && selectedNodeId) {
      return nodes.find((node) => node.id === selectedNodeId) ?? null;
    }
    return null;
  }, [nodes, selectedCanvasNodes, selectedNodeId]);

  const selectedEdge = useMemo(
    () => edges.find((e) => e.id === selectedEdgeId),
    [edges, selectedEdgeId],
  );

  const sourceNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.source),
    [nodes, selectedEdge],
  );
  const targetNode = useMemo(
    () => nodes.find((n) => n.id === selectedEdge?.target),
    [nodes, selectedEdge],
  );

  const subtitle = selectedEdge
    ? "Connection between two steps."
    : isMultiSelect
      ? `${selectedCanvasNodes.length} steps selected on the canvas.`
      : singleNode
        ? "Step settings and configuration."
        : "Schedule this workflow, or select a step, an edge, or multiple steps. Drag \u201cAdd new Step\u201d onto the canvas to choose where it goes.";

  if (isCollapsed) {
    return (
      <aside className="flex w-11 shrink-0 flex-col items-center gap-2 border-l bg-card pt-3.5">
        <Button
          aria-label="Expand panel"
          onClick={() => setIsCollapsed(false)}
          size="icon"
          variant="ghost"
        >
          <PanelRightOpen className="size-4" />
        </Button>
        <AddStepButton compact />
      </aside>
    );
  }

  return (
    <aside className="flex w-[344px] shrink-0 flex-col border-l bg-card">
      <div className="shrink-0 border-b px-3.5 pt-3">
        <div className="flex items-center justify-between gap-2">
          <AddStepButton />
          <Button
            aria-label="Collapse panel"
            onClick={() => setIsCollapsed(true)}
            size="icon"
            variant="ghost"
          >
            <ChevronsRight className="size-4" />
          </Button>
        </div>
        <p className="p-[11px_2px_12px] text-xs text-muted-foreground">
          {subtitle}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-[16px_16px_24px]">
        {selectedEdge ? (
          <SelectedEdgePanel
            edge={selectedEdge}
            sourceTitle={sourceNode?.data.title}
            targetTitle={targetNode?.data.title}
            onEdgeStyleChange={onEdgeStyleChange}
            onEdgeLabelChange={onEdgeLabelChange}
            onEdgeStartLabelChange={onEdgeStartLabelChange}
            onEdgeEndLabelChange={onEdgeEndLabelChange}
            onEdgeLabelBoldChange={onEdgeLabelBoldChange}
            onEdgeLabelFontSizeChange={onEdgeLabelFontSizeChange}
            onDeleteEdge={onDeleteEdge}
          />
        ) : isMultiSelect ? (
          <MultiSelectPanel
            nodes={selectedCanvasNodes}
            isInsideGroup={isInsideGroup}
            groups={groups}
            onMoveToGroup={onMoveToGroup}
            onMoveOutOfGroup={onMoveOutOfGroup}
            autoLayoutDirection={autoLayoutDirection}
            isAutoLayoutRunning={isAutoLayoutRunning}
            onAlignNodes={onAlignNodes}
            onAutoLayoutDirectionChange={onAutoLayoutDirectionChange}
            onAutoLayoutNodes={onAutoLayoutNodes}
            onDeleteNodes={onDeleteNodes}
            onNodesDisabledChange={onNodesDisabledChange}
            onGroupSelectedSteps={onGroupSelectedSteps}
          />
        ) : singleNode ? (
          <SelectedStepPanel
            node={singleNode}
            isInsideGroup={isInsideGroup}
            groups={groups}
            onMoveToGroup={onMoveToGroup}
            onMoveOutOfGroup={onMoveOutOfGroup}
            onOpenConfig={() => openConfigModal(singleNode.id)}
            onNodeTitleChange={onNodeTitleChange}
            onNodeDisabledChange={onNodeDisabledChange}
            onDuplicateNode={onDuplicateNode}
            onDeleteNodes={onDeleteNodes}
            onRenameGroup={onRenameGroup}
            onUngroupGroup={onUngroupGroup}
            onOpenGroup={onOpenGroup}
          />
        ) : (
          <div className="space-y-6">
            <WorkflowStaticAttributesPanel
              value={staticAttributes}
              onChange={onStaticAttributesChange}
            />
            <WorkflowBackgroundTierPanel />
            <WorkflowAiSessionPanel />
          </div>
        )}
      </div>
    </aside>
  );
}
