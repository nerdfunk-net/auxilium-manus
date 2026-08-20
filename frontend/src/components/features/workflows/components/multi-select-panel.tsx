"use client";

import { MultiStepLayoutPanel } from "./multi-step-layout-panel";
import { groupIdFromNodeId } from "../utils/canvas-group-projection";
import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";
import type { ProjectedCanvasNode } from "../types/workflow-canvas";

interface MultiSelectPanelProps {
  nodes: ProjectedCanvasNode[];
  isInsideGroup?: boolean;
  autoLayoutDirection: AutoLayoutDirection;
  isAutoLayoutRunning?: boolean;
  onAlignNodes?: (nodeIds: string[], alignment: NodeAlignment) => void;
  onAutoLayoutDirectionChange: (direction: AutoLayoutDirection) => void;
  onAutoLayoutNodes?: (nodeIds: string[]) => void;
  onDeleteNodes?: (nodeIds: string[]) => void;
  onGroupSelectedSteps?: (nodeIds: string[]) => void;
}

export function MultiSelectPanel({
  nodes,
  isInsideGroup = false,
  autoLayoutDirection,
  isAutoLayoutRunning = false,
  onAlignNodes,
  onAutoLayoutDirectionChange,
  onAutoLayoutNodes,
  onDeleteNodes,
  onGroupSelectedSteps,
}: MultiSelectPanelProps) {
  const nodeIds = nodes.map((node) => node.id);

  return (
    <MultiStepLayoutPanel
      nodes={nodes}
      canGroup={!isInsideGroup && nodes.every((node) => groupIdFromNodeId(node.id) === null)}
      autoLayoutDirection={autoLayoutDirection}
      isAutoLayoutRunning={isAutoLayoutRunning}
      onAlign={(alignment) => onAlignNodes?.(nodeIds, alignment)}
      onAutoLayoutDirectionChange={onAutoLayoutDirectionChange}
      onAutoLayout={() => onAutoLayoutNodes?.(nodeIds)}
      onDelete={() => onDeleteNodes?.(nodeIds)}
      onGroup={() => onGroupSelectedSteps?.(nodeIds)}
    />
  );
}
