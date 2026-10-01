"use client";

import { useCallback, useMemo } from "react";

import { toAbsolutePosition } from "../utils/canvas-containment";
import { validateGroupBoundary } from "../utils/canvas-group-boundary";
import {
  addNodesToGroup,
  groupNodeId,
  removeNodesFromGroups,
  ungroupNode,
} from "../utils/canvas-group-projection";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";
import type { CanvasGroup } from "../types/workflow-canvas";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

// Where a step lands on the root canvas when it is moved out of a group:
// just right of the 320px-wide collapsed group node, stacked per step.
const GROUP_NODE_SPACING_X = 360;
const GROUP_NODE_SPACING_Y = 140;

/** Group/ungroup, rename, open, and append-to-active-group — everything that
 * changes which group a node belongs to, but not the nodes/edges themselves. */
export function useCanvasGroups(core: UseWorkflowCanvasCoreResult) {
  const {
    allNodes,
    setAllNodes,
    groups,
    setGroups,
    activeGroupId,
    selectNode,
    markDirty,
    markError,
    enterGroup,
  } = core;

  const exitToRoot = useWorkflowBuilderStore((state) => state.exitToRoot);

  const appendToActiveGroup = useCallback(
    (nodeId: string) => {
      if (!activeGroupId) return;
      setGroups((current) =>
        current.map((g) =>
          g.id === activeGroupId ? { ...g, nodeIds: [...g.nodeIds, nodeId] } : g,
        ),
      );
    },
    [activeGroupId, setGroups],
  );

  /** Moves steps into an existing group; edges are untouched, ports re-derive. */
  const handleMoveToGroup = useCallback(
    (nodeIds: string[], groupId: string) => {
      const result = addNodesToGroup(groups, allNodes, groupId, nodeIds);
      if (!result.ok) {
        markError(result.reason);
        return;
      }
      setGroups(result.groups);
      selectNode(null);
      markDirty();
    },
    [groups, allNodes, setGroups, selectNode, markDirty, markError],
  );

  /**
   * Moves steps out of their group(s) back onto the root canvas, parked to the
   * right of the group node so they don't land on top of other root steps.
   */
  const handleMoveOutOfGroup = useCallback(
    (nodeIds: string[]) => {
      const moving = new Set(nodeIds);
      const nextGroups = removeNodesFromGroups(groups, nodeIds);
      // Computed outside the state updater so it stays pure (StrictMode re-runs updaters).
      const newPositionById = new Map<string, { x: number; y: number }>();
      for (const group of groups) {
        // A group attached to a background stores a parent-relative position.
        const origin = toAbsolutePosition(
          group.position,
          allNodes.find((n) => n.id === group.parentId)?.position ?? {
            x: 0,
            y: 0,
          },
        );
        group.nodeIds
          .filter((id) => moving.has(id))
          .forEach((id, index) => {
            newPositionById.set(id, {
              x: origin.x + GROUP_NODE_SPACING_X,
              y: origin.y + index * GROUP_NODE_SPACING_Y,
            });
          });
      }
      setAllNodes((current) =>
        current.map((n) => {
          const position = newPositionById.get(n.id);
          return position ? { ...n, position } : n;
        }),
      );
      setGroups(nextGroups);
      if (activeGroupId && !nextGroups.some((g) => g.id === activeGroupId)) {
        exitToRoot();
      }
      selectNode(null);
      markDirty();
    },
    [
      groups,
      allNodes,
      activeGroupId,
      setAllNodes,
      setGroups,
      exitToRoot,
      selectNode,
      markDirty,
    ],
  );

  const handleGroupSelectedSteps = useCallback(
    (nodeIds: string[]) => {
      const result = validateGroupBoundary(nodeIds, groups, allNodes);
      if (!result.valid) {
        markError(result.reason ?? "Cannot group the selected steps.");
        return;
      }

      const memberNodes = allNodes.filter((n) => nodeIds.includes(n.id));
      const avgX =
        memberNodes.reduce((sum, n) => sum + n.position.x, 0) / memberNodes.length;
      const avgY =
        memberNodes.reduce((sum, n) => sum + n.position.y, 0) / memberNodes.length;

      const newGroup: CanvasGroup = {
        id: `group-${crypto.randomUUID()}`,
        title: "New group",
        nodeIds,
        position: { x: avgX, y: avgY },
        parentGroupId: null,
      };
      setGroups((current) => [...current, newGroup]);
      selectNode(groupNodeId(newGroup.id));
      markDirty();
    },
    [allNodes, groups, setGroups, selectNode, markDirty, markError],
  );

  /** Creates an empty container group at `position` (palette "Step Group"). */
  const handleAddContainerGroup = useCallback(
    (position: { x: number; y: number }) => {
      if (activeGroupId) {
        markError("Groups can't be nested yet — add a Step Group from the root canvas.");
        return;
      }
      const newGroup: CanvasGroup = {
        id: `group-${crypto.randomUUID()}`,
        title: "New group",
        nodeIds: [],
        isContainer: true,
        position,
        parentGroupId: null,
      };
      setGroups((current) => [...current, newGroup]);
      selectNode(groupNodeId(newGroup.id));
      markDirty();
    },
    [activeGroupId, setGroups, selectNode, markDirty, markError],
  );

  const handleRenameGroup = useCallback(
    (groupId: string, title: string) => {
      setGroups((current) => current.map((g) => (g.id === groupId ? { ...g, title } : g)));
      markDirty();
    },
    [setGroups, markDirty],
  );

  const handleUngroupGroup = useCallback(
    (groupId: string) => {
      setGroups((current) => ungroupNode(current, groupId));
      selectNode(null);
      markDirty();
    },
    [setGroups, selectNode, markDirty],
  );

  const handleOpenGroup = useCallback(
    (groupId: string) => {
      enterGroup(groupId);
    },
    [enterGroup],
  );

  return useMemo(
    () => ({
      handleAddContainerGroup,
      appendToActiveGroup,
      handleGroupSelectedSteps,
      handleMoveToGroup,
      handleMoveOutOfGroup,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
    }),
    [
      appendToActiveGroup,
      handleGroupSelectedSteps,
      handleAddContainerGroup,
      handleMoveToGroup,
      handleMoveOutOfGroup,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
    ],
  );
}

export type UseCanvasGroupsResult = ReturnType<typeof useCanvasGroups>;
