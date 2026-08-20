"use client";

import { applyNodeChanges } from "@xyflow/react";
import type { NodeChange, NodePositionChange } from "@xyflow/react";
import { useCallback, type Dispatch, type SetStateAction } from "react";

import {
  BACKGROUND_Z_INDEX,
  FOREGROUND_Z_INDEX,
  type CanvasGroup,
  type PersistedCanvasNode,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { resolveContainment } from "../utils/canvas-containment";
import {
  groupIdFromNodeId,
  removeRealNodes,
  ungroupNode,
} from "../utils/canvas-group-projection";

export interface UseCanvasNodeChangesOptions {
  allNodes: PersistedCanvasNode[];
  setAllNodes: Dispatch<SetStateAction<PersistedCanvasNode[]>>;
  allEdges: WorkflowCanvasEdge[];
  setAllEdges: Dispatch<SetStateAction<WorkflowCanvasEdge[]>>;
  groups: CanvasGroup[];
  setGroups: Dispatch<SetStateAction<CanvasGroup[]>>;
  projectedNodes: ProjectedCanvasNode[];
  markDirty: () => void;
}

export function useCanvasNodeChanges({
  allNodes,
  setAllNodes,
  allEdges,
  setAllEdges,
  groups,
  setGroups,
  projectedNodes,
  markDirty,
}: UseCanvasNodeChangesOptions) {
  const handleNodesChange = useCallback(
    (changes: NodeChange<ProjectedCanvasNode>[]) => {
      const previousVisible = projectedNodes;
      const nextVisible = applyNodeChanges(changes, previousVisible);

      const removedIds = changes
        .filter((change) => change.type === "remove")
        .map((change) => change.id);
      const removedRealIds = removedIds.filter((id) => !groupIdFromNodeId(id));
      const removedGroupIds = removedIds
        .map((id) => groupIdFromNodeId(id))
        .filter((id): id is string => id !== null);

      let nextAllNodes = allNodes;
      let nextAllEdges = allEdges;
      let nextGroups = groups;

      if (removedRealIds.length > 0) {
        const result = removeRealNodes(nextAllNodes, nextAllEdges, nextGroups, removedRealIds);
        nextAllNodes = result.nodes;
        nextAllEdges = result.edges;
        nextGroups = result.groups;
      }
      for (const groupId of removedGroupIds) {
        nextGroups = ungroupNode(nextGroups, groupId);
      }

      // Only a drag-end ("dragging: false") position change should trigger a
      // background attach/detach re-evaluation — not every intermediate
      // mousemove, and not unrelated changes (resize, selection).
      const dragEndNodeIds = new Set(
        changes
          .filter(
            (change): change is NodePositionChange =>
              change.type === "position" && change.dragging === false,
          )
          .map((change) => change.id),
      );

      const previousById = new Map(previousVisible.map((node) => [node.id, node]));
      for (const node of nextVisible) {
        if (previousById.get(node.id) === node) continue;

        const groupId = groupIdFromNodeId(node.id);
        if (groupId) {
          const currentGroup = nextGroups.find((g) => g.id === groupId);
          if (
            currentGroup &&
            (currentGroup.position.x !== node.position.x ||
              currentGroup.position.y !== node.position.y)
          ) {
            nextGroups = nextGroups.map((g) =>
              g.id === groupId ? { ...g, position: node.position } : g,
            );
          }
          continue;
        }

        nextAllNodes = nextAllNodes.map((n) => {
          if (n.id !== node.id) return n;
          const updated = node as PersistedCanvasNode;
          if (updated.type === "backgroundNode") {
            const width = Math.round(updated.width ?? updated.measured?.width ?? 0);
            const height = Math.round(
              updated.height ?? updated.measured?.height ?? 0,
            );
            return {
              ...updated,
              zIndex: BACKGROUND_Z_INDEX,
              ...(width > 0 && height > 0
                ? {
                    width,
                    height,
                    data: {
                      ...updated.data,
                      pluginConfig: {
                        ...updated.data.pluginConfig,
                        width,
                        height,
                      },
                    },
                  }
                : {}),
            };
          }
          if (updated.type === "labelNode" || updated.type === "workflowNode") {
            let next = updated;

            if (next.type === "labelNode") {
              const width = Math.round(next.width ?? next.measured?.width ?? 0);
              const height = Math.round(next.height ?? next.measured?.height ?? 0);
              if (width > 0 && height > 0) {
                next = {
                  ...next,
                  width,
                  height,
                  data: {
                    ...next.data,
                    pluginConfig: { ...next.data.pluginConfig, width, height },
                  },
                };
              }
            }

            if (dragEndNodeIds.has(next.id)) {
              const { parentId, position } = resolveContainment(next, nextAllNodes);
              next = { ...next, parentId, position };
            }

            return { ...next, zIndex: next.parentId ? undefined : FOREGROUND_Z_INDEX };
          }
          return updated;
        });
      }

      if (nextAllNodes !== allNodes) setAllNodes(nextAllNodes);
      if (nextAllEdges !== allEdges) setAllEdges(nextAllEdges);
      if (nextGroups !== groups) setGroups(nextGroups);

      const hasContentChange = changes.some((c) => c.type !== "select");
      if (hasContentChange) markDirty();
    },
    [
      projectedNodes,
      allNodes,
      allEdges,
      groups,
      setAllNodes,
      setAllEdges,
      setGroups,
      markDirty,
    ],
  );

  return { handleNodesChange };
}
