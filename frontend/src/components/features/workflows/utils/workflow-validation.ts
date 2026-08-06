import {
  isCanvasDecorationKind,
  type CanvasGroup,
  type WorkflowCanvasEdge,
  type PersistedCanvasNode,
} from "../types/workflow-canvas";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import { validateGroupBoundary } from "./canvas-group-boundary";

const EMPTY_GROUPS: CanvasGroup[] = [];
const EMPTY_STATIC_ATTRIBUTES: StaticAttributeDef[] = [];

function validateStaticAttributes(attributes: StaticAttributeDef[]): string[] {
  const issues: string[] = [];
  const seen = new Set<string>();
  for (const attr of attributes) {
    const trimmed = attr.name.trim();
    if (!trimmed) {
      issues.push("A static attribute is missing a name.");
      continue;
    }
    if (seen.has(trimmed)) {
      issues.push(`Duplicate static attribute name: "${trimmed}".`);
      continue;
    }
    seen.add(trimmed);
    if (attr.default === undefined || attr.default === null) continue;
    const typeOk =
      (attr.type === "string" && typeof attr.default === "string") ||
      (attr.type === "number" && typeof attr.default === "number") ||
      (attr.type === "boolean" && typeof attr.default === "boolean");
    if (!typeOk) {
      issues.push(`Static attribute "${trimmed}": default does not match type "${attr.type}".`);
    }
  }
  return issues;
}

export function validateCanvasWorkflow(
  nodes: PersistedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  groups: CanvasGroup[] = EMPTY_GROUPS,
  staticAttributes: StaticAttributeDef[] = EMPTY_STATIC_ATTRIBUTES,
) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const danglingEdges = edges.filter(
    (edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target),
  );
  const hasExecutableStep = nodes.some(
    (node) => !isCanvasDecorationKind(node.data.kind),
  );

  const groupIssues = groups
    .filter((group) => {
      // Re-run the linear-chain boundary check against the group's *current*
      // membership. Interactive edits (add/remove members) don't block on this
      // — this is the single checkpoint where group integrity is enforced.
      const otherGroups = groups.filter((g) => g.id !== group.id);
      const result = validateGroupBoundary(group.nodeIds, edges, otherGroups, nodes);
      return !result.valid;
    })
    .map(
      (group) =>
        `Group "${group.title}" no longer has a single entry and exit — fix connections or ungroup before saving.`,
    );

  const staticAttributeIssues = validateStaticAttributes(staticAttributes);

  const issues = [
    ...(hasExecutableStep ? [] : ["Workflow has no steps."]),
    ...danglingEdges.map(
      (edge) => `Edge ${edge.id} references a missing workflow step.`,
    ),
    ...groupIssues,
    ...staticAttributeIssues,
  ];

  return {
    isValid:
      hasExecutableStep &&
      danglingEdges.length === 0 &&
      groupIssues.length === 0 &&
      staticAttributeIssues.length === 0,
    issues,
  };
}
