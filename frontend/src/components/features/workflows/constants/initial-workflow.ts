import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";

export const initialWorkflowNodes: WorkflowCanvasNode[] = [
  {
    id: "device-selection",
    type: "workflowNode",
    position: { x: 80, y: 210 },
    data: {
      kind: "device-selection",
      title: "Device Selection",
      description: "Choose target devices from inventory.",
      status: "ready",
    },
  },
  {
    id: "ssh-login",
    type: "workflowNode",
    position: { x: 390, y: 210 },
    data: {
      kind: "ssh-login",
      title: "SSH Login",
      description: "Open a managed CLI session.",
      status: "draft",
    },
  },
  {
    id: "run-command",
    type: "workflowNode",
    position: { x: 700, y: 210 },
    data: {
      kind: "run-command",
      title: "Run Command",
      description: "Collect the running configuration.",
      command: "show running-config",
      status: "draft",
    },
  },
  {
    id: "condition",
    type: "workflowNode",
    position: { x: 1010, y: 210 },
    data: {
      kind: "condition",
      title: "Validate Output",
      description: "Check whether command output is usable.",
      condition: "output.length > 0",
      status: "warning",
    },
  },
  {
    id: "store-artifact",
    type: "workflowNode",
    position: { x: 1320, y: 120 },
    data: {
      kind: "store-artifact",
      title: "Store Backup",
      description: "Persist configuration as an artifact.",
      artifactPath: "/backups/{device}/running.cfg",
      status: "draft",
    },
  },
  {
    id: "result",
    type: "workflowNode",
    position: { x: 1320, y: 310 },
    data: {
      kind: "result",
      title: "Result",
      description: "Expose status, metadata, and content.",
      status: "success",
    },
  },
];

export const initialWorkflowEdges: WorkflowCanvasEdge[] = [
  {
    id: "device-selection-to-ssh-login",
    source: "device-selection",
    target: "ssh-login",
    animated: false,
  },
  {
    id: "ssh-login-to-run-command",
    source: "ssh-login",
    target: "run-command",
    animated: false,
  },
  {
    id: "run-command-to-condition",
    source: "run-command",
    target: "condition",
    animated: false,
  },
  {
    id: "condition-to-store-artifact",
    source: "condition",
    target: "store-artifact",
    label: "valid",
    animated: false,
  },
  {
    id: "condition-to-result",
    source: "condition",
    target: "result",
    label: "failed",
    animated: false,
  },
];
