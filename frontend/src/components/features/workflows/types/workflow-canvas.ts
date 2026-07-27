import type { Edge, Node } from "@xyflow/react";

import type { Capability } from "@/lib/capability-types";

// Plugin ids are loaded from the backend registry at startup, so node kinds are dynamic.
export type WorkflowNodeKind = string;

export interface WorkflowOutcomeField {
  name: string;
}

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

export type EdgeStyle = "straight" | "smooth";

/** Default edge path style for new connections and unset `edgeStyle`. */
export const DEFAULT_EDGE_STYLE: EdgeStyle = "smooth";

export interface WorkflowEdgeData extends Record<string, unknown> {
  waypoints?: Waypoint[];
  edgeStyle?: EdgeStyle;
  /** Set only on synthetic group-boundary proxy edges in the root projection. */
  realEdgeId?: string;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData, "workflowNode">;
export type LabelCanvasNode = Node<WorkflowNodeData, "labelNode">;
export type BackgroundCanvasNode = Node<WorkflowNodeData, "backgroundNode">;

/** Persisted canvas nodes: executable steps plus canvas-only decorations. */
export type PersistedCanvasNode =
  | WorkflowCanvasNode
  | LabelCanvasNode
  | BackgroundCanvasNode;

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

export function reactFlowTypeForKind(kind: string): PersistedCanvasNode["type"] {
  if (kind === "label") return "labelNode";
  if (kind === "background") return "backgroundNode";
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

/** Stacking: backgrounds stay under steps/labels (React Flow paints later equal-z nodes on top). */
export const BACKGROUND_Z_INDEX = 0;
export const FOREGROUND_Z_INDEX = 1;

export const LABEL_FONT_STACKS: Record<string, string> = {
  sans: 'ui-sans-serif, system-ui, sans-serif',
  serif: 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
};

/** Keep background nodes first so equal-z paint order cannot cover steps. */
export function sortNodesBackgroundsBehind<T extends { type?: string }>(
  nodes: T[],
): T[] {
  return [...nodes].sort((a, b) => {
    const aRank = a.type === "backgroundNode" ? 0 : 1;
    const bRank = b.type === "backgroundNode" ? 0 : 1;
    return aRank - bRank;
  });
}