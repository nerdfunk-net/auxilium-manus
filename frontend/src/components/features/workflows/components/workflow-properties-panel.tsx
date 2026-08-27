"use client";

import {
  ChevronsRight,
  Layers,
  PanelRightOpen,
  Sliders,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { MultiSelectPanel } from "./multi-select-panel";
import { SelectedEdgePanel } from "./selected-edge-panel";
import { SelectedStepPanel } from "./selected-step-panel";
import { StepCatalog } from "./step-catalog";
import { WorkflowBackgroundTierPanel } from "./workflow-background-tier-panel";
import { WorkflowSchedulePanel } from "./workflow-schedule-panel";
import { WorkflowStaticAttributesPanel } from "./workflow-static-attributes-panel";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  type EdgeStyle,
  type ProjectedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";

const EMPTY_EDGES: WorkflowCanvasEdge[] = [];

interface WorkflowPropertiesPanelProps {
  nodes: ProjectedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  plugins: PluginDefinition[];
  isPluginsLoading: boolean;
  pluginErrorMessage?: string;
  isInsideGroup?: boolean;
  onAddStep: (step: StepPayload) => void;
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
  plugins,
  isPluginsLoading,
  pluginErrorMessage,
  isInsideGroup = false,
  onAddStep,
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
  onGroupSelectedSteps,
  onRenameGroup,
  onUngroupGroup,
  onOpenGroup,
  staticAttributes,
  onStaticAttributesChange,
}: WorkflowPropertiesPanelProps) {
  const rightPanelTab = useWorkflowBuilderStore((state) => state.rightPanelTab);
  const setRightPanelTab = useWorkflowBuilderStore((state) => state.setRightPanelTab);
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

  const subtitle =
    rightPanelTab === "steps"
      ? "Drag onto the canvas, or click to add."
      : selectedEdge
        ? "Connection between two steps."
        : isMultiSelect
          ? `${selectedCanvasNodes.length} steps selected on the canvas.`
          : singleNode
            ? "Step settings and configuration."
            : "Schedule this workflow, or select a step, an edge, or multiple steps.";

  if (isCollapsed) {
    return (
      <aside className="flex w-11 shrink-0 flex-col items-center border-l bg-card pt-3.5">
        <Button
          aria-label="Expand panel"
          onClick={() => setIsCollapsed(false)}
          size="icon"
          variant="ghost"
        >
          <PanelRightOpen className="size-4" />
        </Button>
      </aside>
    );
  }

  return (
    <aside className="flex w-[344px] shrink-0 flex-col border-l bg-card">
      <div className="shrink-0 border-b px-3.5 pt-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex gap-1 rounded-[10px] border bg-muted p-[3px]">
            <button
              className={cn(
                "flex items-center gap-1.5 rounded-[7px] px-[14px] py-[6px] text-[13px] font-medium transition-colors",
                rightPanelTab === "steps"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setRightPanelTab("steps")}
              type="button"
            >
              <Layers className="size-3.5" aria-hidden />
              Steps
            </button>
            <button
              className={cn(
                "flex items-center gap-1.5 rounded-[7px] px-[14px] py-[6px] text-[13px] font-medium transition-colors",
                rightPanelTab === "properties"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setRightPanelTab("properties")}
              type="button"
            >
              <Sliders className="size-3.5" aria-hidden />
              Properties
            </button>
          </div>
          <Button
            aria-label="Collapse panel"
            onClick={() => setIsCollapsed(true)}
            size="icon"
            variant="ghost"
          >
            <ChevronsRight className="size-4" />
          </Button>
        </div>
        <p className="p-[11px_2px_12px] text-xs text-muted-foreground">{subtitle}</p>
      </div>

      {rightPanelTab === "steps" ? (
        <StepCatalog
          errorMessage={pluginErrorMessage}
          isLoading={isPluginsLoading}
          onAddStep={onAddStep}
          plugins={plugins}
        />
      ) : (
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
              autoLayoutDirection={autoLayoutDirection}
              isAutoLayoutRunning={isAutoLayoutRunning}
              onAlignNodes={onAlignNodes}
              onAutoLayoutDirectionChange={onAutoLayoutDirectionChange}
              onAutoLayoutNodes={onAutoLayoutNodes}
              onDeleteNodes={onDeleteNodes}
              onGroupSelectedSteps={onGroupSelectedSteps}
            />
          ) : singleNode ? (
            <SelectedStepPanel
              node={singleNode}
              onOpenConfig={() => openConfigModal(singleNode.id)}
              onNodeTitleChange={onNodeTitleChange}
              onDuplicateNode={onDuplicateNode}
              onDeleteNodes={onDeleteNodes}
              onRenameGroup={onRenameGroup}
              onUngroupGroup={onUngroupGroup}
              onOpenGroup={onOpenGroup}
            />
          ) : (
            <div className="space-y-6">
              <WorkflowSchedulePanel />
              <WorkflowStaticAttributesPanel
                value={staticAttributes}
                onChange={onStaticAttributesChange}
              />
              <WorkflowBackgroundTierPanel />
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
