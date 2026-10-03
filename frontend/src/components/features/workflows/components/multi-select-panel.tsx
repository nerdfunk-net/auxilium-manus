"use client";

import {
  MoveToGroupControl,
  type MoveTargetGroup,
} from "./move-to-group-control";
import { MultiStepLayoutPanel } from "./multi-step-layout-panel";
import { groupIdFromNodeId } from "../utils/canvas-group-projection";
import type { AutoLayoutDirection } from "../utils/auto-layout";
import type { NodeAlignment } from "../utils/node-alignment";
import type { ProjectedCanvasNode } from "../types/workflow-canvas";

interface MultiSelectPanelProps {
  nodes: ProjectedCanvasNode[];
  isInsideGroup?: boolean;
  groups: MoveTargetGroup[];
  onMoveToGroup?: (nodeIds: string[], groupId: string) => void;
  onMoveOutOfGroup?: (nodeIds: string[]) => void;
  autoLayoutDirection: AutoLayoutDirection;
  isAutoLayoutRunning?: boolean;
  onAlignNodes?: (nodeIds: string[], alignment: NodeAlignment) => void;
  onAutoLayoutDirectionChange: (direction: AutoLayoutDirection) => void;
  onAutoLayoutNodes?: (nodeIds: string[]) => void;
  onDeleteNodes?: (nodeIds: string[]) => void;
  onNodesDisabledChange?: (nodeIds: string[], disabled: boolean) => void;
  onGroupSelectedSteps?: (nodeIds: string[]) => void;
}

export function MultiSelectPanel({
  nodes,
  isInsideGroup = false,
  groups,
  onMoveToGroup,
  onMoveOutOfGroup,
  autoLayoutDirection,
  isAutoLayoutRunning = false,
  onAlignNodes,
  onAutoLayoutDirectionChange,
  onAutoLayoutNodes,
  onDeleteNodes,
  onNodesDisabledChange,
  onGroupSelectedSteps,
}: MultiSelectPanelProps) {
  const nodeIds = nodes.map((node) => node.id);
  const canMove = nodes.every(
    (node) =>
      groupIdFromNodeId(node.id) === null && node.data.kind !== "background",
  );

  return (
    <>
      <MultiStepLayoutPanel
        nodes={nodes}
        canGroup={
          !isInsideGroup &&
          nodes.every((node) => groupIdFromNodeId(node.id) === null)
        }
        autoLayoutDirection={autoLayoutDirection}
        isAutoLayoutRunning={isAutoLayoutRunning}
        onAlign={(alignment) => onAlignNodes?.(nodeIds, alignment)}
        onAutoLayoutDirectionChange={onAutoLayoutDirectionChange}
        onAutoLayout={() => onAutoLayoutNodes?.(nodeIds)}
        onDelete={() => onDeleteNodes?.(nodeIds)}
        onSetDisabled={(disabled) => onNodesDisabledChange?.(nodeIds, disabled)}
        onGroup={() => onGroupSelectedSteps?.(nodeIds)}
      />
      {canMove ? (
        <MoveToGroupControl
          nodeIds={nodeIds}
          groups={groups}
          isInsideGroup={isInsideGroup}
          onMoveToGroup={onMoveToGroup}
          onMoveOutOfGroup={onMoveOutOfGroup}
        />
      ) : null}
    </>
  );
}
