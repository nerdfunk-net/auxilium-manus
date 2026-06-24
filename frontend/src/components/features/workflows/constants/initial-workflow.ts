import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";

export const initialWorkflowNodes: WorkflowCanvasNode[] = [
  {
    id: "get-nautobot-devices",
    type: "workflowNode",
    position: { x: 80, y: 210 },
    data: {
      kind: "get-nautobot-devices",
      title: "Get from Nautobot",
      description: "Choose target devices from inventory.",
      artifactType: "inventory_selector",
      requires: [],
      produces: ["identity"],
      mandatoryInputs: [],
      outcomes: [
        { name: "success" },
        { name: "failure" },
      ],
      status: "ready",
    },
  },
  {
    id: "get-configs",
    type: "workflowNode",
    position: { x: 390, y: 210 },
    data: {
      kind: "get-configs",
      title: "Get Configs",
      description: "Retrieve device configuration.",
      artifactType: "configuration_retrieval",
      mandatoryInputs: [{ name: "selected_devices", dataType: "device_list" }],
      outcomes: [
        { name: "success", dataType: "config_output" },
        { name: "failure", dataType: "device_list" },
      ],
      status: "draft",
    },
  },
  {
    id: "condition",
    type: "workflowNode",
    position: { x: 700, y: 210 },
    data: {
      kind: "condition",
      title: "Validate Output",
      description: "Check whether configuration output is usable.",
      artifactType: "control_flow",
      mandatoryInputs: [{ name: "input_reference", dataType: "config_output" }],
      condition: "output.length > 0",
      outcomes: [
        { name: "true", dataType: "config_output" },
        { name: "false", dataType: "config_output" },
        { name: "failure", dataType: "config_output" },
      ],
      status: "warning",
    },
  },
  {
    id: "store-artifact",
    type: "workflowNode",
    position: { x: 1010, y: 120 },
    data: {
      kind: "store-artifact",
      title: "Store Backup",
      description: "Persist configuration as an artifact.",
      artifactType: "persistent_artifact",
      mandatoryInputs: [{ name: "content_reference", dataType: "config_output" }],
      artifactPath: "/backups/{device}/running.cfg",
      outcomes: [
        { name: "success", dataType: "artifact_ref" },
        { name: "failure", dataType: "config_output" },
      ],
      status: "draft",
    },
  },
  {
    id: "result",
    type: "workflowNode",
    position: { x: 1010, y: 310 },
    data: {
      kind: "result",
      title: "Result",
      description: "Expose status, metadata, and content.",
      artifactType: "result",
      mandatoryInputs: [{ name: "metadata", dataType: "config_output" }],
      outcomes: [],
      status: "success",
    },
  },
];

export const initialWorkflowEdges: WorkflowCanvasEdge[] = [
  {
    id: "get-nautobot-devices-to-get-configs",
    type: "waypoint",
    source: "get-nautobot-devices",
    sourceHandle: "success",
    target: "get-configs",
    targetHandle: "input",
    animated: false,
  },
  {
    id: "get-configs-to-condition",
    type: "waypoint",
    source: "get-configs",
    sourceHandle: "success",
    target: "condition",
    animated: false,
  },
  {
    id: "condition-to-store-artifact",
    type: "waypoint",
    source: "condition",
    sourceHandle: "true",
    target: "store-artifact",
    label: "valid",
    animated: false,
  },
  {
    id: "condition-to-result",
    type: "waypoint",
    source: "condition",
    sourceHandle: "false",
    target: "result",
    label: "failed",
    animated: false,
  },
];
