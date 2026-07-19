import {
  GROUP_EDGE_ID_PREFIX,
  GROUP_NODE_ID_PREFIX,
  type CanvasGroup,
  type GroupCanvasNode,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from "../types/workflow-canvas";

export function groupNodeId(groupId: string): string {
  return `${GROUP_NODE_ID_PREFIX}${groupId}`;
}

export function groupIdFromNodeId(nodeId: string): string | null {
  return nodeId.startsWith(GROUP_NODE_ID_PREFIX)
    ? nodeId.slice(GROUP_NODE_ID_PREFIX.length)
    : null;
}

export function groupEdgeId(realEdgeId: string): string {
  return `${GROUP_EDGE_ID_PREFIX}${realEdgeId}`;
}

export function isGroupCanvasNode(
  node: ProjectedCanvasNode,
): node is GroupCanvasNode {
  return node.data.kind === "__canvas-group__";
}

export function findGroupContainingNode(
  groups: CanvasGroup[],
  nodeId: string,
): CanvasGroup | undefined {
  return groups.find((group) => group.nodeIds.includes(nodeId));
}

export interface ProjectedCanvas {
  nodes: ProjectedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  /** Maps synthetic group-node id -> CanvasGroup id */
  groupNodeIds: Map<string, string>;
}

function synthesizeGroupNode(
  group: CanvasGroup,
  allNodes: WorkflowCanvasNode[],
): GroupCanvasNode {
  const entryNode = allNodes.find(
    (n) => n.id === group.entryNodeId && group.nodeIds.includes(n.id),
  );
  const exitNode = allNodes.find(
    (n) => n.id === group.exitNodeId && group.nodeIds.includes(n.id),
  );

  return {
    id: groupNodeId(group.id),
    type: "groupNode",
    position: group.position,
    data: {
      kind: "__canvas-group__",
      title: group.title,
      memberCount: group.nodeIds.length,
      groupId: group.id,
      requires: entryNode?.data.requires,
      requiresParsed: entryNode?.data.requiresParsed,
      outcomes: [{ name: "success" }],
      produces: exitNode?.data.produces,
      producesParsed: exitNode?.data.producesParsed,
    },
  };
}

/**
 * Derives the rendered (visible) canvas for the given navigation level from the
 * authoritative flat graph. `allNodes`/`allEdges`/`groups` are the only stateful
 * arrays; this function is a pure, memoizable derivation and must never be
 * stored in its own state.
 */
export function projectCanvasView(
  allNodes: WorkflowCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  activeGroupId: string | null,
): ProjectedCanvas {
  if (activeGroupId !== null) {
    const group = groups.find((g) => g.id === activeGroupId);
    if (!group) {
      return { nodes: [], edges: [], groupNodeIds: new Map() };
    }
    const memberIds = new Set(group.nodeIds);
    const nodes = allNodes.filter((n) => memberIds.has(n.id));
    const edges = allEdges.filter(
      (e) => memberIds.has(e.source) && memberIds.has(e.target),
    );
    return { nodes, edges, groupNodeIds: new Map() };
  }

  const groupedNodeIds = new Set<string>();
  for (const group of groups) {
    for (const id of group.nodeIds) {
      groupedNodeIds.add(id);
    }
  }

  const visibleStepNodes = allNodes.filter((n) => !groupedNodeIds.has(n.id));
  const groupNodeIds = new Map<string, string>();
  const groupNodes: GroupCanvasNode[] = groups.map((group) => {
    const synthetic = synthesizeGroupNode(group, allNodes);
    groupNodeIds.set(synthetic.id, group.id);
    return synthetic;
  });

  const groupIdByNodeId = new Map<string, string>();
  for (const group of groups) {
    for (const id of group.nodeIds) {
      groupIdByNodeId.set(id, group.id);
    }
  }

  const edges: WorkflowCanvasEdge[] = [];
  for (const edge of allEdges) {
    const sourceGroupId = groupIdByNodeId.get(edge.source);
    const targetGroupId = groupIdByNodeId.get(edge.target);

    if (sourceGroupId && targetGroupId) {
      // Internal to the same group: omitted. Crossing two different groups is
      // rejected at group-creation time, so this case should not arise in v1.
      continue;
    }

    if (targetGroupId) {
      edges.push({
        ...edge,
        id: groupEdgeId(edge.id),
        target: groupNodeId(targetGroupId),
        targetHandle: "input",
        data: { ...edge.data, realEdgeId: edge.id },
      });
      continue;
    }

    if (sourceGroupId) {
      edges.push({
        ...edge,
        id: groupEdgeId(edge.id),
        source: groupNodeId(sourceGroupId),
        sourceHandle: "success",
        data: { ...edge.data, realEdgeId: edge.id },
      });
      continue;
    }

    edges.push(edge);
  }

  return {
    nodes: [...visibleStepNodes, ...groupNodes],
    edges,
    groupNodeIds,
  };
}

/**
 * Removes real step nodes (and edges touching them) from the authoritative
 * graph. If a removed node belonged to a group, it is dropped from that
 * group's membership; groups left with fewer than two members are dissolved.
 * Used by both the trash-button delete path and the keyboard delete path so
 * the two never diverge (see FEATURE-GROUPING.md Hard Part 2).
 */
export function removeRealNodes(
  allNodes: WorkflowCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  nodeIds: string[],
): {
  nodes: WorkflowCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
} {
  const idSet = new Set(nodeIds);
  const nodes = allNodes.filter((n) => !idSet.has(n.id));
  const edges = allEdges.filter(
    (e) => !idSet.has(e.source) && !idSet.has(e.target),
  );
  const nextGroups = groups
    .map((group) => ({
      ...group,
      nodeIds: group.nodeIds.filter((id) => !idSet.has(id)),
    }))
    .filter((group) => group.nodeIds.length >= 2);

  return { nodes, edges, groups: nextGroups };
}

/**
 * Dissolves a group: the CanvasGroup entry is removed but its member steps
 * and edges are left untouched in the authoritative graph.
 */
export function ungroupNode(
  groups: CanvasGroup[],
  groupIdToRemove: string,
): CanvasGroup[] {
  return groups.filter((group) => group.id !== groupIdToRemove);
}

/**
 * Repairs orphaned group metadata after load: drops references to nodes that
 * no longer exist and dissolves groups left with fewer than two members.
 */
export function repairOrphanGroups(
  allNodes: WorkflowCanvasNode[],
  groups: CanvasGroup[],
): CanvasGroup[] {
  const nodeIdSet = new Set(allNodes.map((n) => n.id));
  return groups
    .map((group) => ({
      ...group,
      nodeIds: group.nodeIds.filter((id) => nodeIdSet.has(id)),
    }))
    .filter((group) => group.nodeIds.length >= 2);
}
