import type {
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";

export function validateCanvasWorkflow(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const danglingEdges = edges.filter(
    (edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target),
  );
  const issues = [
    ...(nodes.length === 0 ? ["Workflow has no steps."] : []),
    ...danglingEdges.map(
      (edge) => `Edge ${edge.id} references a missing workflow step.`,
    ),
  ];

  return {
    isValid: nodes.length > 0 && danglingEdges.length === 0,
    issues,
  };
}
