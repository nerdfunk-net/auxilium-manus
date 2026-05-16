import type {
  WorkflowDefinition,
  WorkflowStepDefinition,
} from "../types/workflow-definition";
import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
  WorkflowNodeKind,
} from "../types/workflow-canvas";

const outputKeyByKind: Record<WorkflowNodeKind, string> = {
  trigger: "trigger",
  "device-selection": "devices",
  "ssh-login": "session",
  "run-command": "commandOutput",
  condition: "branch",
  "store-artifact": "artifact",
  result: "result",
};

const inputKeyByKind: Record<WorkflowNodeKind, string> = {
  trigger: "trigger",
  "device-selection": "inventory",
  "ssh-login": "devices",
  "run-command": "session",
  condition: "content",
  "store-artifact": "content",
  result: "metadata",
};

export function mapCanvasToWorkflowDefinition(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  options: { id: string; name: string },
): WorkflowDefinition {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const steps: WorkflowStepDefinition[] = nodes.map((node) => {
    const incomingEdges = edges.filter((edge) => edge.target === node.id);

    return {
      id: node.id,
      type: node.data.kind,
      name: node.data.title,
      description: node.data.description,
      dependsOn: incomingEdges.map((edge) => edge.source),
      inputMappings: incomingEdges.map((edge) => {
        const sourceNode = nodesById.get(edge.source);

        return {
          sourceStepId: edge.source,
          sourceKey: sourceNode
            ? outputKeyByKind[sourceNode.data.kind]
            : "unknown",
          targetKey: inputKeyByKind[node.data.kind],
        };
      }),
      metadata: {
        ...(node.data.command ? { command: node.data.command } : {}),
        ...(node.data.condition ? { condition: node.data.condition } : {}),
        ...(node.data.artifactPath
          ? { artifactPath: node.data.artifactPath }
          : {}),
      },
    };
  });

  return {
    id: options.id,
    name: options.name,
    version: 1,
    deviceSelection: {
      strategy: "manual",
      deviceIds: [],
    },
    steps,
  };
}
