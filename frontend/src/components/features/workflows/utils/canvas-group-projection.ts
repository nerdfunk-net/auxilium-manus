import {
  GROUP_EDGE_ID_PREFIX,
  GROUP_NODE_ID_PREFIX,
  sortNodesForContainment,
  type CanvasGroup,
  type GroupCanvasNode,
  type PersistedCanvasNode,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { toAbsolutePosition } from "./canvas-containment";
import {
  deriveGroupPorts,
  GROUP_INPUT_HANDLE_PREFIX,
  GROUP_OUTPUT_HANDLE_PREFIX,
  type GroupPort,
} from "./canvas-group-ports";

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

/** Container groups persist at any size; selection groups dissolve below two members. */
export function groupSurvivesMembership(group: CanvasGroup): boolean {
  return group.isContainer === true || group.nodeIds.length >= 2;
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

// Matches GroupNode's fixed `w-80 h-32` footprint. The synthetic group node is
// rebuilt from scratch on every projection (it isn't a persisted node React
// Flow can keep re-measuring across renders), so without an explicit size it
// briefly looks "unmeasured" and disappears until the next measurement pass —
// visible as a flicker whenever allNodes/groups changes (e.g. while dragging).
// Declaring the size up front skips that measure-then-reveal cycle entirely.
const GROUP_NODE_WIDTH = 320;
const GROUP_NODE_HEIGHT = 128;

function portLabel(port: GroupPort, allNodes: PersistedCanvasNode[], withHandle: boolean) {
  const title = allNodes.find((n) => n.id === port.innerNodeId)?.data.title ?? port.innerNodeId;
  return withHandle ? `${title} · ${port.innerHandle}` : title;
}

function synthesizeGroupNode(
  group: CanvasGroup,
  allNodes: PersistedCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
): GroupCanvasNode {
  const ports = deriveGroupPorts(group.nodeIds, allEdges);
  const nodeById = new Map(allNodes.map((n) => [n.id, n]));
  const inputNodes = ports.inputs.flatMap((p) => nodeById.get(p.innerNodeId) ?? []);
  const outputNodes = ports.outputs.flatMap((p) => nodeById.get(p.innerNodeId) ?? []);

  return {
    id: groupNodeId(group.id),
    type: "groupNode",
    position: group.position,
    width: GROUP_NODE_WIDTH,
    height: GROUP_NODE_HEIGHT,
    measured: { width: GROUP_NODE_WIDTH, height: GROUP_NODE_HEIGHT },
    selected: group.selected,
    data: {
      kind: "__canvas-group__",
      title: group.title,
      memberCount: group.nodeIds.length,
      groupId: group.id,
      requires: inputNodes.flatMap((n) => n.data.requires ?? []),
      requiresParsed: inputNodes.flatMap((n) => n.data.requiresParsed ?? []),
      outcomes: [{ name: "success" }],
      produces: outputNodes.flatMap((n) => n.data.produces ?? []),
      producesParsed: outputNodes.flatMap((n) => n.data.producesParsed ?? []),
      inputPorts: ports.inputs.map((p) => ({
        handleId: `${GROUP_INPUT_HANDLE_PREFIX}${p.edgeId}`,
        edgeId: p.edgeId,
        label: portLabel(p, allNodes, false),
      })),
      outputPorts: ports.outputs.map((p) => ({
        handleId: `${GROUP_OUTPUT_HANDLE_PREFIX}${p.edgeId}`,
        edgeId: p.edgeId,
        label: portLabel(p, allNodes, true),
      })),
      incomeHandleSide: group.incomeHandleSide,
      outcomeHandleSide: group.outcomeHandleSide,
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
  allNodes: PersistedCanvasNode[],
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

    // Presentation-only: mark the member steps that own a boundary port.
    const ports = deriveGroupPorts(group.nodeIds, allEdges);
    const entryIds = new Set(ports.inputs.map((p) => p.innerNodeId));
    const exitHandlesByNode = new Map<string, string[]>();
    for (const port of ports.outputs) {
      exitHandlesByNode.set(port.innerNodeId, [
        ...(exitHandlesByNode.get(port.innerNodeId) ?? []),
        port.innerHandle,
      ]);
    }

    const nodes = allNodes
      .filter((n) => memberIds.has(n.id))
      .map((n) => {
        const isEntry = entryIds.has(n.id);
        const exitHandles = exitHandlesByNode.get(n.id);
        if (!isEntry && !exitHandles) return n;
        return {
          ...n,
          data: {
            ...n.data,
            ...(isEntry ? { isGroupEntryPoint: true } : {}),
            ...(exitHandles
              ? { isGroupExitPoint: true, groupExitHandles: exitHandles }
              : {}),
          },
        };
      });
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
    const synthetic = synthesizeGroupNode(group, allNodes, allEdges);
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
      if (sourceGroupId === targetGroupId) continue; // internal to one group
      edges.push({
        ...edge,
        id: groupEdgeId(edge.id),
        source: groupNodeId(sourceGroupId),
        sourceHandle: `${GROUP_OUTPUT_HANDLE_PREFIX}${edge.id}`,
        target: groupNodeId(targetGroupId),
        targetHandle: `${GROUP_INPUT_HANDLE_PREFIX}${edge.id}`,
        data: { ...edge.data, realEdgeId: edge.id },
      });
      continue;
    }

    if (targetGroupId) {
      edges.push({
        ...edge,
        id: groupEdgeId(edge.id),
        target: groupNodeId(targetGroupId),
        targetHandle: `${GROUP_INPUT_HANDLE_PREFIX}${edge.id}`,
        data: { ...edge.data, realEdgeId: edge.id },
      });
      continue;
    }

    if (sourceGroupId) {
      edges.push({
        ...edge,
        id: groupEdgeId(edge.id),
        source: groupNodeId(sourceGroupId),
        sourceHandle: `${GROUP_OUTPUT_HANDLE_PREFIX}${edge.id}`,
        data: { ...edge.data, realEdgeId: edge.id },
      });
      continue;
    }

    edges.push(edge);
  }

  return {
    nodes: sortNodesForContainment([...visibleStepNodes, ...groupNodes]),
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
  allNodes: PersistedCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  nodeIds: string[],
): {
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
} {
  const idSet = new Set(nodeIds);

  // Deleting a background detaches its children rather than deleting them:
  // keep the step on canvas at its current absolute position, un-parented.
  const removedPositionById = new Map(
    allNodes.filter((n) => idSet.has(n.id)).map((n) => [n.id, n.position]),
  );
  const withDetachedChildren = allNodes.map((n) => {
    if (!n.parentId || !idSet.has(n.parentId) || idSet.has(n.id)) return n;
    const parentPosition = removedPositionById.get(n.parentId) ?? { x: 0, y: 0 };
    return {
      ...n,
      parentId: undefined,
      position: toAbsolutePosition(n.position, parentPosition),
    };
  });

  const nodes = withDetachedChildren.filter((n) => !idSet.has(n.id));
  const edges = allEdges.filter(
    (e) => !idSet.has(e.source) && !idSet.has(e.target),
  );
  const nextGroups = groups
    .map((group) => ({
      ...group,
      nodeIds: group.nodeIds.filter((id) => !idSet.has(id)),
    }))
    .filter(groupSurvivesMembership);

  return { nodes, edges, groups: nextGroups };
}

export type AddToGroupResult =
  | { ok: true; groups: CanvasGroup[] }
  | { ok: false; reason: string };

/**
 * Moves real steps into an existing group. Only membership changes — edges are
 * untouched, so boundary ports re-derive on their own. Steps already in another
 * group are moved (removed from it first; a group left with < 2 members is
 * dissolved).
 */
export function addNodesToGroup(
  groups: CanvasGroup[],
  allNodes: PersistedCanvasNode[],
  groupId: string,
  nodeIds: string[],
): AddToGroupResult {
  if (!groups.some((g) => g.id === groupId)) {
    return { ok: false, reason: "The target group no longer exists." };
  }
  const idSet = new Set(nodeIds);
  if (allNodes.some((n) => idSet.has(n.id) && !!n.parentId)) {
    return { ok: false, reason: "Steps inside a background can't be added to a group yet." };
  }

  const stripped = removeNodesFromGroups(
    groups.map((g) =>
      g.id === groupId ? { ...g, nodeIds: g.nodeIds.filter((id) => !idSet.has(id)) } : g,
    ),
    nodeIds,
    groupId,
  );
  return {
    ok: true,
    groups: stripped.map((g) =>
      g.id === groupId ? { ...g, nodeIds: [...g.nodeIds, ...nodeIds] } : g,
    ),
  };
}

/**
 * Drops steps from whichever group holds them (they return to the root canvas).
 * Groups left with fewer than two members are dissolved. `keepGroupId` exempts
 * one group from dissolution while it is mid-update.
 */
export function removeNodesFromGroups(
  groups: CanvasGroup[],
  nodeIds: string[],
  keepGroupId?: string,
): CanvasGroup[] {
  const idSet = new Set(nodeIds);
  return groups
    .map((g) => ({ ...g, nodeIds: g.nodeIds.filter((id) => !idSet.has(id)) }))
    .filter((g) => g.id === keepGroupId || groupSurvivesMembership(g));
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
  allNodes: PersistedCanvasNode[],
  groups: CanvasGroup[],
): CanvasGroup[] {
  const nodeIdSet = new Set(allNodes.map((n) => n.id));
  return groups
    .map((group) => ({
      ...group,
      nodeIds: group.nodeIds.filter((id) => nodeIdSet.has(id)),
    }))
    .filter(groupSurvivesMembership);
}
