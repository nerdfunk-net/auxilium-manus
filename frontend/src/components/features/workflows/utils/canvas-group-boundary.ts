import type { CanvasGroup, PersistedCanvasNode } from "../types/workflow-canvas";

export interface GroupBoundaryResult {
  valid: boolean;
  reason?: string;
}

/**
 * Validates a selection for grouping. A group is a pure organising container:
 * any set of steps qualifies, regardless of shape (branches, fan-in/out,
 * multiple outputs). Boundary ports are derived from the edges at render time
 * (see canvas-group-ports.ts), so no chain / single-entry / single-exit rule
 * applies.
 */
export function validateGroupBoundary(
  selectedIds: string[],
  existingGroups: CanvasGroup[],
  nodes: PersistedCanvasNode[],
): GroupBoundaryResult {
  if (selectedIds.length < 2) {
    return {
      valid: false,
      reason: "Select at least two steps to create a group.",
    };
  }

  const idSet = new Set(selectedIds);

  const alreadyGrouped = existingGroups.some((group) =>
    group.nodeIds.some((id) => idSet.has(id)),
  );
  if (alreadyGrouped) {
    return {
      valid: false,
      reason: "One or more selected steps already belong to another group.",
    };
  }

  const hasBackgroundChild = nodes.some((n) => idSet.has(n.id) && !!n.parentId);
  if (hasBackgroundChild) {
    return {
      valid: false,
      reason: "Steps inside a background can't be added to a group yet.",
    };
  }

  return { valid: true };
}
