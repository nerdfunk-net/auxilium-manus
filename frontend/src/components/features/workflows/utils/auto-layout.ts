import type { ElkExtendedEdge, ElkNode, ElkPort, LayoutOptions } from "elkjs/lib/elk-api";

import {
  isCanvasDecorationKind,
  type HandleSide,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { nodeHeight, nodeWidth, parentOffset } from "./canvas-coordinates";

export type AutoLayoutDirection = "horizontal" | "vertical";

/** Circular funnel node footprint (`size-10` = 40px), used only as a fallback
 * for a funnel that hasn't been measured by React Flow yet — the shared
 * `nodeWidth`/`nodeHeight` fallback is tuned for workflowNode and would be
 * badly wrong for a 40x40 node. */
const FUNNEL_NODE_SIZE = 40;

const ELK_DIRECTION: Record<AutoLayoutDirection, string> = {
  horizontal: "RIGHT",
  vertical: "DOWN",
};

const HANDLE_SIDE_TO_ELK: Record<HandleSide, string> = {
  left: "WEST",
  right: "EAST",
  top: "NORTH",
  bottom: "SOUTH",
};

const DEFAULT_INCOME_SIDE: HandleSide = "left";
const DEFAULT_OUTCOME_SIDE: HandleSide = "right";

const ROOT_LAYOUT_OPTIONS: LayoutOptions = {
  "elk.algorithm": "layered",
  "elk.layered.spacing.nodeNodeBetweenLayers": "72",
  "elk.spacing.nodeNode": "48",
  "elk.spacing.componentComponent": "80",
};

function portId(nodeId: string, handleId: string): string {
  return `${nodeId}__${handleId}`;
}

function resolvePortReference(nodeId: string, handleId: string | null | undefined): string {
  return handleId ? portId(nodeId, handleId) : nodeId;
}

interface PortSpec {
  handleId: string;
  side: string;
}

/**
 * Port assignment is keyed on node *kind* (`node.type`), never on which
 * `data` fields happen to be present — `FunnelCanvasNode` reuses
 * `WorkflowNodeData` and can carry a stale `outcomes`/`requires` array left
 * over from before it became a funnel (see LAYOUT.md "Funnel node data
 * staleness"), so branching on `data.outcomes` would give a funnel spurious
 * multi-outcome ports.
 */
function resolvePorts(node: ProjectedCanvasNode): { target: PortSpec | null; sources: PortSpec[] } {
  if (node.type === "funnelNode") {
    const incomeSide = HANDLE_SIDE_TO_ELK[node.data.incomeHandleSide ?? DEFAULT_INCOME_SIDE];
    const outcomeSide = HANDLE_SIDE_TO_ELK[node.data.outcomeHandleSide ?? DEFAULT_OUTCOME_SIDE];
    return {
      target: { handleId: "input", side: incomeSide },
      sources: [{ handleId: "output", side: outcomeSide }],
    };
  }

  if (node.type === "groupNode") {
    const hasTarget =
      (node.data.requires?.length ?? 0) > 0 || (node.data.requiresParsed?.length ?? 0) > 0;
    return {
      target: hasTarget ? { handleId: "input", side: "WEST" } : null,
      sources: [{ handleId: "success", side: "EAST" }],
    };
  }

  // workflowNode (and any other non-decoration, non-funnel, non-group kind).
  const incomeSide = HANDLE_SIDE_TO_ELK[node.data.incomeHandleSide ?? DEFAULT_INCOME_SIDE];
  const outcomeSide = HANDLE_SIDE_TO_ELK[node.data.outcomeHandleSide ?? DEFAULT_OUTCOME_SIDE];
  const hasTarget = (node.data.requires?.length ?? 0) > 0;
  const outcomes = node.data.outcomes ?? [];
  return {
    target: hasTarget ? { handleId: "input", side: incomeSide } : null,
    sources: outcomes.map((outcome) => ({ handleId: outcome.name, side: outcomeSide })),
  };
}

function resolveNodeSize(node: ProjectedCanvasNode): { width: number; height: number } {
  if (node.type === "funnelNode") {
    return {
      width: node.measured?.width ?? node.width ?? FUNNEL_NODE_SIZE,
      height: node.measured?.height ?? node.height ?? FUNNEL_NODE_SIZE,
    };
  }
  return { width: nodeWidth(node), height: nodeHeight(node) };
}

function buildElkPorts(node: ProjectedCanvasNode): ElkPort[] {
  const { target, sources } = resolvePorts(node);
  const specs = target ? [target, ...sources] : sources;
  return specs.map((spec, index) => ({
    id: portId(node.id, spec.handleId),
    layoutOptions: {
      "elk.port.side": spec.side,
      "elk.port.index": String(index),
    },
  }));
}

function buildElkNode(
  node: ProjectedCanvasNode,
  fixedPosition?: { x: number; y: number },
): ElkNode {
  const size = resolveNodeSize(node);
  const ports = buildElkPorts(node);
  return {
    id: node.id,
    width: size.width,
    height: size.height,
    ports,
    ...(ports.length > 1 ? { layoutOptions: { "elk.portConstraints": "FIXED_ORDER" } } : {}),
    ...(fixedPosition ? { x: fixedPosition.x, y: fixedPosition.y } : {}),
  };
}

function absolutePosition(
  node: ProjectedCanvasNode,
  nodesById: Map<string, ProjectedCanvasNode>,
): { x: number; y: number } {
  const offset = parentOffset(node, nodesById);
  return { x: node.position.x + offset.x, y: node.position.y + offset.y };
}

export interface BuildElkGraphOptions {
  direction: AutoLayoutDirection;
  /**
   * `null` lays out every non-decoration node passed in. A non-null array
   * scopes the layout to just those node ids — any *other* node with an edge
   * into/out of the selection is included in the graph as a pinned anchor
   * (see LAYOUT.md "Selection scope: boundary edges") purely to influence
   * ranking; its own position is excluded from `movableNodeIds` and is never
   * written back by `applyElkLayout`.
   */
  selectedNodeIds: string[] | null;
}

export interface BuiltElkGraph {
  graph: ElkNode;
  /** Node ids ELK is free to move — excludes pinned selection-boundary anchors. */
  movableNodeIds: Set<string>;
}

export function buildElkGraph(
  nodes: ProjectedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  options: BuildElkGraphOptions,
): BuiltElkGraph {
  const layoutable = nodes.filter((node) => !isCanvasDecorationKind(node.data.kind));
  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  const selectedIds = options.selectedNodeIds ? new Set(options.selectedNodeIds) : null;
  const movable = selectedIds ? layoutable.filter((node) => selectedIds.has(node.id)) : layoutable;
  const movableNodeIds = new Set(movable.map((node) => node.id));

  const pinned: ProjectedCanvasNode[] = [];
  if (selectedIds) {
    const pinnedIds = new Set<string>();
    for (const edge of edges) {
      const sourceMovable = movableNodeIds.has(edge.source);
      const targetMovable = movableNodeIds.has(edge.target);
      if (sourceMovable === targetMovable) continue; // both inside or both outside the selection
      const externalId = sourceMovable ? edge.target : edge.source;
      if (pinnedIds.has(externalId) || movableNodeIds.has(externalId)) continue;
      const externalNode = nodesById.get(externalId);
      if (!externalNode || isCanvasDecorationKind(externalNode.data.kind)) continue;
      pinnedIds.add(externalId);
      pinned.push(externalNode);
    }
  }

  const graphNodeIds = new Set<string>([...movableNodeIds, ...pinned.map((node) => node.id)]);

  const elkNodes: ElkNode[] = [
    ...movable.map((node) => buildElkNode(node)),
    ...pinned.map((node) => buildElkNode(node, absolutePosition(node, nodesById))),
  ];

  const elkEdges: ElkExtendedEdge[] = edges
    .filter((edge) => graphNodeIds.has(edge.source) && graphNodeIds.has(edge.target))
    .filter((edge) => movableNodeIds.has(edge.source) || movableNodeIds.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      sources: [resolvePortReference(edge.source, edge.sourceHandle)],
      targets: [resolvePortReference(edge.target, edge.targetHandle)],
    }));

  const layoutOptions: LayoutOptions = {
    ...ROOT_LAYOUT_OPTIONS,
    "elk.direction": ELK_DIRECTION[options.direction],
  };
  if (pinned.length > 0) {
    // ELK's layered algorithm has no hard "pin node in place" primitive.
    // Interactive mode biases crossing minimization toward each node's given
    // x/y instead of guaranteeing them — the closest available approximation
    // (see LAYOUT.md "Selection scope: boundary edges").
    layoutOptions["elk.interactiveLayout"] = "true";
    layoutOptions["elk.layered.crossingMinimization.strategy"] = "INTERACTIVE";
  }

  return {
    graph: {
      id: "__root__",
      layoutOptions,
      children: elkNodes,
      edges: elkEdges,
    },
    movableNodeIds,
  };
}

export function applyElkLayout(
  nodes: ProjectedCanvasNode[],
  elkResult: ElkNode,
  movableNodeIds: Set<string>,
): ProjectedCanvasNode[] {
  const positionById = new Map<string, { x: number; y: number }>();
  for (const child of elkResult.children ?? []) {
    if (!movableNodeIds.has(child.id)) continue;
    if (typeof child.x !== "number" || typeof child.y !== "number") continue;
    positionById.set(child.id, { x: child.x, y: child.y });
  }

  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  return nodes.map((node) => {
    const absolute = positionById.get(node.id);
    if (!absolute) return node;
    const offset = parentOffset(node, nodesById);
    return {
      ...node,
      position: { x: absolute.x - offset.x, y: absolute.y - offset.y },
    };
  });
}

export interface AutoLayoutResult {
  nodes: ProjectedCanvasNode[];
  /** Node ids whose position actually changed — used to clear stale edge
   * waypoints and scope the post-layout `fitView`. */
  movedNodeIds: string[];
}

/**
 * The only exported entry point for running a layout pass — owns the dynamic
 * `elkjs` import (kept out of the initial bundle; this only ever runs on a
 * user click) and the ELK instance lifecycle.
 */
export async function runAutoLayout(
  nodes: ProjectedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  direction: AutoLayoutDirection,
  selectedNodeIds: string[] | null,
): Promise<AutoLayoutResult> {
  // Matches alignCanvasNodes' `targets.length < 2` guard for a *selection*
  // scope; the "lay out everything in view" scope (selectedNodeIds === null)
  // still runs with as few as one node/edge.
  if (selectedNodeIds !== null && selectedNodeIds.length < 2) {
    return { nodes, movedNodeIds: [] };
  }

  const { graph, movableNodeIds } = buildElkGraph(nodes, edges, { direction, selectedNodeIds });
  if (movableNodeIds.size === 0) {
    return { nodes, movedNodeIds: [] };
  }

  const ELK = (await import("elkjs/lib/elk.bundled.js")).default;
  const elk = new ELK();
  const result = await elk.layout(graph);

  return {
    nodes: applyElkLayout(nodes, result, movableNodeIds),
    movedNodeIds: [...movableNodeIds],
  };
}
