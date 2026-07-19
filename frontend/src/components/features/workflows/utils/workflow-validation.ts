import type {
  CanvasGroup,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";
import { validateGroupBoundary } from "./canvas-group-boundary";

const EMPTY_GROUPS: CanvasGroup[] = [];

export function validateCanvasWorkflow(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  groups: CanvasGroup[] = EMPTY_GROUPS,
) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const danglingEdges = edges.filter(
    (edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target),
  );

  const groupIssues = groups
    .filter((group) => {
      // Re-run the linear-chain boundary check against the group's *current*
      // membership. Interactive edits (add/remove members) don't block on this
      // — this is the single checkpoint where group integrity is enforced.
      const otherGroups = groups.filter((g) => g.id !== group.id);
      const result = validateGroupBoundary(group.nodeIds, edges, otherGroups);
      return !result.valid;
    })
    .map(
      (group) =>
        `Group "${group.title}" no longer has a single entry and exit — fix connections or ungroup before saving.`,
    );

  const issues = [
    ...(nodes.length === 0 ? ["Workflow has no steps."] : []),
    ...danglingEdges.map(
      (edge) => `Edge ${edge.id} references a missing workflow step.`,
    ),
    ...groupIssues,
  ];

  return {
    isValid: nodes.length > 0 && danglingEdges.length === 0 && groupIssues.length === 0,
    issues,
  };
}
