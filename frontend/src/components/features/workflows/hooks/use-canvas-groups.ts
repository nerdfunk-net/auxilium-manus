"use client";

import { useCallback, useMemo } from "react";

import { validateGroupBoundary } from "../utils/canvas-group-boundary";
import { groupNodeId, ungroupNode } from "../utils/canvas-group-projection";
import type { CanvasGroup } from "../types/workflow-canvas";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

/** Group/ungroup, rename, open, and append-to-active-group — everything that
 * changes which group a node belongs to, but not the nodes/edges themselves. */
export function useCanvasGroups(core: UseWorkflowCanvasCoreResult) {
  const {
    allNodes,
    allEdges,
    groups,
    setGroups,
    activeGroupId,
    selectNode,
    markDirty,
    markError,
    enterGroup,
  } = core;

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

  const handleGroupSelectedSteps = useCallback(
    (nodeIds: string[]) => {
      const result = validateGroupBoundary(nodeIds, allEdges, groups, allNodes);
      if (!result.valid || !result.entryNodeId || !result.exitNodeId) {
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
        entryNodeId: result.entryNodeId,
        exitNodeId: result.exitNodeId,
        position: { x: avgX, y: avgY },
        parentGroupId: null,
      };
      setGroups((current) => [...current, newGroup]);
      selectNode(groupNodeId(newGroup.id));
      markDirty();
    },
    [allNodes, allEdges, groups, setGroups, selectNode, markDirty, markError],
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
      appendToActiveGroup,
      handleGroupSelectedSteps,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
    }),
    [
      appendToActiveGroup,
      handleGroupSelectedSteps,
      handleRenameGroup,
      handleUngroupGroup,
      handleOpenGroup,
    ],
  );
}

export type UseCanvasGroupsResult = ReturnType<typeof useCanvasGroups>;
