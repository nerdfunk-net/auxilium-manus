import {
  isCanvasDecorationKind,
  isFunnelKind,
  type CanvasGroup,
  type WorkflowCanvasEdge,
  type PersistedCanvasNode,
} from "../types/workflow-canvas";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import { validateGroupBoundary } from "./canvas-group-boundary";
import { validateGetFromUserNodes } from "./run-input-attributes";

const EMPTY_GROUPS: CanvasGroup[] = [];
const EMPTY_STATIC_ATTRIBUTES: StaticAttributeDef[] = [];

// Config fields whose value points at a static attribute by name — see
// backend/workflow_steps/registry.yaml (every field ending in "_param" that
// isn't get-from-user's own device_param, handled separately in
// run-input-attributes.ts). Used only to give a validation error a "used by"
// hint; not exhaustive beyond what the registry currently defines.
const REFERENCE_PARAM_CONFIG_KEYS = ["inventory_param", "credential_param"] as const;

/** Titles of nodes whose config points at `paramName` via one of
 * REFERENCE_PARAM_CONFIG_KEYS — so a bad static attribute's error can say
 * which step(s) on the canvas actually reference it. */
function describeReferencingNodes(nodes: PersistedCanvasNode[], paramName: string): string {
  const titles: string[] = [];
  for (const node of nodes) {
    const config = node.data?.pluginConfig;
    if (!config) continue;
    const references = REFERENCE_PARAM_CONFIG_KEYS.some(
      (key) => typeof config[key] === "string" && (config[key] as string).trim() === paramName,
    );
    if (references) {
      titles.push(node.data.title || node.id);
    }
  }
  return titles.length > 0 ? ` (used by ${titles.map((t) => `"${t}"`).join(", ")})` : "";
}

function validateStaticAttributes(
  attributes: StaticAttributeDef[],
  nodes: PersistedCanvasNode[],
): string[] {
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
    const isInt = typeof attr.default === "number" && Number.isInteger(attr.default);
    const typeOk =
      (attr.type === "string" && typeof attr.default === "string") ||
      (attr.type === "number" && typeof attr.default === "number") ||
      (attr.type === "boolean" && typeof attr.default === "boolean") ||
      (attr.type === "reference" &&
        ((attr.ref_kind === "inventory" && isInt) ||
          (attr.ref_kind === "credential" && typeof attr.default === "string")));
    if (!typeOk) {
      const usedBy = describeReferencingNodes(nodes, trimmed);
      issues.push(
        `Static attribute "${trimmed}": default does not match type "${attr.type}"${usedBy}.`,
      );
    }
  }
  return issues;
}

export function validateCanvasWorkflow(
  nodes: PersistedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  groups: CanvasGroup[] = EMPTY_GROUPS,
  staticAttributes: StaticAttributeDef[] = EMPTY_STATIC_ATTRIBUTES,
  // Save must allow a genuinely empty draft (e.g. a blank canvas created so
  // an AI-updates session can be enabled on it before any steps exist — see
  // doc/ai_collaboration/PROCESS.md) while Run must still refuse an empty
  // workflow, since there is nothing to execute. Default true preserves
  // existing behavior for every call site that doesn't opt out.
  { requireSteps = true }: { requireSteps?: boolean } = {},
) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const danglingEdges = edges.filter(
    (edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target),
  );
  const hasExecutableStep = nodes.some(
    (node) =>
      !isCanvasDecorationKind(node.data.kind) &&
      !isFunnelKind(node.data.kind) &&
      node.data.disabled !== true,
  );
  const missingSteps = requireSteps && !hasExecutableStep;

  const funnelIssues = nodes
    .filter((node) => isFunnelKind(node.data.kind))
    .filter((node) => edges.filter((edge) => edge.source === node.id).length !== 1)
    .map((node) => `Funnel "${node.id}" must connect to exactly one destination.`);

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

  const staticAttributeIssues = validateStaticAttributes(staticAttributes, nodes);
  const getFromUserIssues = validateGetFromUserNodes(nodes);

  const issues = [
    ...(missingSteps ? ["Workflow has no steps."] : []),
    ...danglingEdges.map(
      (edge) => `Edge ${edge.id} references a missing workflow step.`,
    ),
    ...groupIssues,
    ...staticAttributeIssues,
    ...getFromUserIssues,
    ...funnelIssues,
  ];

  return {
    isValid:
      !missingSteps &&
      danglingEdges.length === 0 &&
      groupIssues.length === 0 &&
      staticAttributeIssues.length === 0 &&
      getFromUserIssues.length === 0 &&
      funnelIssues.length === 0,
    issues,
  };
}
