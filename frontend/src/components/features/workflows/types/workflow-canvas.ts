import type { Edge, Node } from "@xyflow/react";

// Plugin ids are loaded from the backend registry at startup, so node kinds are dynamic.
export type WorkflowNodeKind = string;

export interface WorkflowNodeData extends Record<string, unknown> {
  kind: WorkflowNodeKind;
  stepUuid?: string;
  title: string;
  description: string;
  artifactType?: string;
  mandatoryInputs?: string[];
  status?: "ready" | "draft" | "running" | "success" | "warning";
  command?: string;
  condition?: string;
  artifactPath?: string;
  outcomes?: string[];
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
