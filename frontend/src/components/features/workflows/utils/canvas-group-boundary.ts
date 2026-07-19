import type {
  CanvasGroup,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";

export interface GroupBoundaryResult {
  valid: boolean;
  entryNodeId?: string;
  exitNodeId?: string;
  reason?: string;
}

/**
 * Topologically sorts `nodeIds` using only edges internal to the selection.
 * Returns null if the internal subgraph contains a cycle.
 */
function topologicalOrder(
  nodeIds: string[],
  edges: WorkflowCanvasEdge[],
): string[] | null {
  const idSet = new Set(nodeIds);
  const internalEdges = edges.filter(
    (edge) => idSet.has(edge.source) && idSet.has(edge.target),
  );

  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();
  for (const id of nodeIds) {
    inDegree.set(id, 0);
    adjacency.set(id, []);
  }
  for (const edge of internalEdges) {
    adjacency.get(edge.source)?.push(edge.target);
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
  }

  const queue = nodeIds.filter((id) => (inDegree.get(id) ?? 0) === 0);
  const order: string[] = [];
  while (queue.length > 0) {
    const id = queue.shift()!;
    order.push(id);
    for (const next of adjacency.get(id) ?? []) {
      const nextDegree = (inDegree.get(next) ?? 0) - 1;
      inDegree.set(next, nextDegree);
      if (nextDegree === 0) {
        queue.push(next);
      }
    }
  }

  return order.length === nodeIds.length ? order : null;
}

/**
 * Validates a selection against the v1 "linear chain" grouping rule: the
 * selection must be a single sequential chain with exactly one entry point
 * from outside the selection and exactly one exit point to outside it.
 */
export function validateGroupBoundary(
  selectedIds: string[],
  edges: WorkflowCanvasEdge[],
  existingGroups: CanvasGroup[],
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

  const order = topologicalOrder(selectedIds, edges);
  if (!order) {
    return {
      valid: false,
      reason: "Selected steps must form a chain without cycles.",
    };
  }

  for (let i = 0; i < order.length - 1; i++) {
    const hasSequentialEdge = edges.some(
      (edge) => edge.source === order[i] && edge.target === order[i + 1],
    );
    if (!hasSequentialEdge) {
      return {
        valid: false,
        reason:
          'Grouping currently supports sequential step chains. Selected steps must form a single chain with one input and one output.',
      };
    }
  }

  const entryNodeId = order[0];
  const exitNodeId = order[order.length - 1];

  const incomingFromOutside = edges.filter(
    (edge) => idSet.has(edge.target) && !idSet.has(edge.source),
  );
  const outgoingToOutside = edges.filter(
    (edge) => idSet.has(edge.source) && !idSet.has(edge.target),
  );

  if (incomingFromOutside.length > 1 || incomingFromOutside.some((e) => e.target !== entryNodeId)) {
    return {
      valid: false,
      reason: "Group must have exactly one input from outside the group.",
    };
  }
  if (outgoingToOutside.length > 1 || outgoingToOutside.some((e) => e.source !== exitNodeId)) {
    return {
      valid: false,
      reason: "Group must have exactly one output to outside the group.",
    };
  }

  return { valid: true, entryNodeId, exitNodeId };
}
