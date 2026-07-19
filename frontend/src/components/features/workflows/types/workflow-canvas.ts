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

export interface WorkflowEdgeData extends Record<string, unknown> {
  waypoints?: Waypoint[];
  edgeStyle?: EdgeStyle;
  /** Set only on synthetic group-boundary proxy edges in the root projection. */
  realEdgeId?: string;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData, "workflowNode">;
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

/** Nodes flowing through the canvas after group projection: real steps or synthetic groups. */
export type ProjectedCanvasNode = WorkflowCanvasNode | GroupCanvasNode;

export const GROUP_NODE_ID_PREFIX = "__group__";
export const GROUP_EDGE_ID_PREFIX = "__group-edge__";
