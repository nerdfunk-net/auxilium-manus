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
  description: string;
  artifactType?: string;
  requires?: Capability[];
  requiresParsed?: string[];
  produces?: Capability[];
  producesParsed?: string[];
  consumes?: Capability[];
  status?: "ready" | "draft" | "running" | "success" | "warning";
  command?: string;
  condition?: string;
  artifactPath?: string;
  outcomes?: WorkflowOutcomeField[];
  pluginConfig?: Record<string, unknown>;
}

export interface Waypoint {
  x: number;
  y: number;
}

export type EdgeStyle = "straight" | "smooth";

export interface WorkflowEdgeData extends Record<string, unknown> {
  waypoints?: Waypoint[];
  edgeStyle?: EdgeStyle;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData, "workflowNode">;
export type WorkflowCanvasEdge = Edge<WorkflowEdgeData, "waypoint">;
