import type { Edge, Node } from "@xyflow/react";

import type { Capability } from "@/lib/capability-types";

// Plugin ids are loaded from the backend registry at startup, so node kinds are dynamic.
export type WorkflowNodeKind = string;

export interface WorkflowOutcomeField {
  name: string;
}

/** Which side of the node a handle attaches to. */
export type HandleSide = "top" | "bottom" | "left" | "right";

export interface WorkflowNodeData extends Record<string, unknown> {
  kind: WorkflowNodeKind;
  stepUuid?: string;
  title: string;
  overview?: string;
  description: string;
  artifactType?: string;
  requires?: Capability[];
  requiresParsed?: string[];
  produces?: Capability[];
  producesParsed?: string[];
  consumes?: Capability[];
  command?: string;
  condition?: string;
  artifactPath?: string;
  outcomes?: WorkflowOutcomeField[];
  pluginConfig?: Record<string, unknown>;
  /** Side the input handle attaches to. Default "left". Must differ from outcomeHandleSide. */
  incomeHandleSide?: HandleSide;
  /** Side the outcome handles attach to. Default "right". Must differ from incomeHandleSide. */
  outcomeHandleSide?: HandleSide;
  /**
   * View-only annotations set by projectCanvasView's inner-group projection —
   * never present on allNodes/persisted canvas_nodes, only on the projected
   * copy, so they mark the entry/exit step of the group currently being viewed.
   */
  isGroupEntryPoint?: boolean;
  isGroupExitPoint?: boolean;
  /** The outcome handle name of the exit step's edge that leaves the group. */
  groupExitHandle?: string;
}

export interface Waypoint {
  x: number;
  y: number;
}

export interface StepPayload {
  kind: WorkflowNodeKind;
  title: string;
  overview: string;
  description: string;
  artifactType: string;
  requires: Capability[];
  requiresParsed: string[];
  produces: Capability[];
  producesParsed: string[];
  consumes: Capability[];
  outcomes: WorkflowOutcomeField[];
}

/**
 * Edge path style. Names match React Flow's built-in edge types
 * (https://reactflow.dev/examples/edges/edge-types) except "straight", which
 * in this app is a custom editable polyline (draggable bend points) rather
 * than React Flow's plain point-to-point straight line.
 */
export type EdgeStyle = "straight" | "bezier" | "step" | "smoothstep";

/** Default edge path style for new connections and unset `edgeStyle`. */
export const DEFAULT_EDGE_STYLE: EdgeStyle = "bezier";

/** Default font size (px) for debug edge labels when `labelFontSize` is unset. */
export const DEFAULT_EDGE_LABEL_FONT_SIZE = 10;

export interface WorkflowEdgeData extends Record<string, unknown> {
  waypoints?: Waypoint[];
  edgeStyle?: EdgeStyle;
  /** Free-text debug annotation shown at the edge midpoint via EdgeLabelRenderer. */
  label?: string;
  /** Free-text debug annotation shown near the edge's source end via EdgeLabelRenderer. */
  startLabel?: string;
  /** Free-text debug annotation shown near the edge's target end via EdgeLabelRenderer. */
  endLabel?: string;
  /** Bold styling applied to all debug labels on this edge. Default false. */
  labelBold?: boolean;
  /** Font size (px) applied to all debug labels on this edge. Default 10. */
  labelFontSize?: number;
  /** Set only on synthetic group-boundary proxy edges in the root projection. */
  realEdgeId?: string;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData, "workflowNode">;
export type LabelCanvasNode = Node<WorkflowNodeData, "labelNode">;
export type BackgroundCanvasNode = Node<WorkflowNodeData, "backgroundNode">;
export type FunnelCanvasNode = Node<WorkflowNodeData, "funnelNode">;

/** Persisted canvas nodes: executable steps plus canvas-only decorations. */
export type PersistedCanvasNode =
  | WorkflowCanvasNode
  | LabelCanvasNode
  | BackgroundCanvasNode
  | FunnelCanvasNode;

export type WorkflowCanvasEdge = Edge<WorkflowEdgeData, "waypoint">;

export interface CanvasGroup {
  /** Stable id, e.g. "group-1". Never reuse after delete. */
  id: string;
  /** Display title on the collapsed Group node. */
  title: string;
  /** Member step node ids (must all exist in canvas_nodes). */
  nodeIds: string[];
  /**
   * Cached boundary ids, validated strictly at group creation. NOT re-validated
   * synchronously on every member change — best-effort cache, re-checked strictly
   * at save/run time (see workflow-validation.ts).
   */
  entryNodeId: string;
  exitNodeId: string;
  /** Position of the collapsed Group node on the root canvas. */
  position: { x: number; y: number };
  /** Reserved for v2 nested groups. Always null in v1. */
  parentGroupId: string | null;
}

export interface GroupNodeData extends Record<string, unknown> {
  kind: "__canvas-group__";
  title: string;
  memberCount: number;
  groupId: string;
  requires?: Capability[];
  requiresParsed?: string[];
  outcomes?: WorkflowOutcomeField[];
  produces?: Capability[];
  producesParsed?: string[];
  consumes?: Capability[];
}

export type GroupCanvasNode = Node<GroupNodeData, "groupNode">;

/** Nodes flowing through the canvas after group projection: real steps, decorations, or synthetic groups. */
export type ProjectedCanvasNode = PersistedCanvasNode | GroupCanvasNode;

export const GROUP_NODE_ID_PREFIX = "__group__";
export const GROUP_EDGE_ID_PREFIX = "__group-edge__";

/** Canvas decoration kinds — no handles, not executed at runtime. */
export const CANVAS_DECORATION_KINDS = new Set(["label", "background"]);

export function isCanvasDecorationKind(kind: string | undefined): boolean {
  return !!kind && CANVAS_DECORATION_KINDS.has(kind);
}

/**
 * The funnel kind is deliberately NOT part of CANVAS_DECORATION_KINDS: unlike
 * label/background it accepts connection handles (many in, one out) and is
 * spliced — not just filtered — out of the graph before execution (see
 * StepRunner._resolve_funnels). Kept as its own check so callers don't
 * accidentally lump it in with edge-rejecting decorations.
 */
export const FUNNEL_KIND = "funnel";

export function isFunnelKind(kind: string | undefined): boolean {
  return kind === FUNNEL_KIND;
}

export function reactFlowTypeForKind(kind: string): PersistedCanvasNode["type"] {
  if (kind === "label") return "labelNode";
  if (kind === "background") return "backgroundNode";
  if (kind === FUNNEL_KIND) return "funnelNode";
  return "workflowNode";
}

export const DEFAULT_LABEL_CONFIG = {
  text: "Label",
  font_size: 16,
  font_family: "sans",
  bold: false,
  color: "#0f172a",
  width: 200,
  height: 40,
} as const;

export const DEFAULT_BACKGROUND_CONFIG = {
  color: "#e2e8f0",
  width: 480,
  height: 320,
} as const;

/**
 * Stacking order in React Flow (edges and nodes are sibling layers):
 * background (-1) < edges (0) < steps/labels (1).
 * A non-negative background z-index paints above the edge SVG and hides wires.
 */
export const BACKGROUND_Z_INDEX = -1;
export const FOREGROUND_Z_INDEX = 1;
export const EDGE_Z_INDEX = 0;

export const LABEL_FONT_STACKS: Record<string, string> = {
  sans: 'ui-sans-serif, system-ui, sans-serif',
  serif: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
};

/**
 * Keep background nodes first in the array. This serves two purposes:
 * 1. Cosmetic — a step not yet attached to a background but visually overlapping
 *    it should still paint above (equal-z paint order otherwise follows array order).
 * 2. Structural — React Flow requires a parent node to appear before its children.
 *    Since only `backgroundNode`s can be a `parentId` target (single-level nesting,
 *    see canvas-containment.ts), sorting all backgrounds before all non-backgrounds
 *    is sufficient to guarantee every child appears after its parent.
 */
export function sortNodesForContainment<T extends { type?: string }>(
  nodes: T[],
): T[] {
  return [...nodes].sort((a, b) => {
    const aRank = a.type === "backgroundNode" ? 0 : 1;
    const bRank = b.type === "backgroundNode" ? 0 : 1;
    return aRank - bRank;
  });
}

/** True if `node` is currently attached as a child of a background node. */
export function hasBackgroundParent(
  node: PersistedCanvasNode,
): node is PersistedCanvasNode & { parentId: string } {
  return typeof node.parentId === "string" && node.parentId.length > 0;
}