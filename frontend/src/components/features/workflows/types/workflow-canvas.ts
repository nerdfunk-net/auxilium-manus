import type { Edge, Node } from "@xyflow/react";

export type WorkflowNodeKind =
  | "trigger"
  | "device-selection"
  | "ssh-login"
  | "run-command"
  | "condition"
  | "store-artifact"
  | "result";

export interface WorkflowNodeData extends Record<string, unknown> {
  kind: WorkflowNodeKind;
  title: string;
  description: string;
  status?: "ready" | "draft" | "running" | "success" | "warning";
  command?: string;
  condition?: string;
  artifactPath?: string;
}

export type WorkflowCanvasNode = Node<WorkflowNodeData, "workflowNode">;
export type WorkflowCanvasEdge = Edge;
