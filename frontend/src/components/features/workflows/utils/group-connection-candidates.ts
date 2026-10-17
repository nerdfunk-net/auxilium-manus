import { isCompatible } from "@/lib/capability-types";

import {
  isCanvasDecorationKind,
  isFunnelKind,
  type CanvasGroup,
  type PersistedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { getOutcomeProvides, type OutcomeProvides } from "./capability-graph";
import {
  deriveGroupPorts,
  GROUP_INPUT_HANDLE_PREFIX,
  GROUP_OUTPUT_HANDLE_PREFIX,
} from "./canvas-group-ports";

export interface GroupConnectionCandidate {
  /** Real member step the edge should attach to. */
  nodeId: string;
  /** Handle on that step (target handle for inputs, outcome name for outputs). */
  handle: string;
  title: string;
  kind: string;
}

interface CandidateQuery {
  /** "input": the group is the connection target. "output": it is the source. */
  side: "input" | "output";
  group: CanvasGroup;
  /** Handle the user dropped on; "in:<edgeId>" / "out:<edgeId>" pins an existing port. */
  groupHandleId: string | null | undefined;
  /** The real step on the other side, or null when it is itself a group (no compat filter). */
  otherEnd: { nodeId: string; handle: string | null | undefined } | null;
  allNodes: readonly PersistedCanvasNode[];
  allEdges: readonly WorkflowCanvasEdge[];
  /** `computeOutcomeProvides` over the FLAT graph (never the collapsed projection). */
  flatProvides: Map<string, OutcomeProvides>;
}

const DEFAULT_TARGET_HANDLE = "input";
const DEFAULT_OUTCOME = "success";

function isRealStep(node: PersistedCanvasNode): boolean {
  return !isCanvasDecorationKind(node.data.kind) && !isFunnelKind(node.data.kind);
}

function requirementsOf(node: PersistedCanvasNode) {
  return {
    capabilities: node.data.requires ?? [],
    parsedKeys: node.data.requiresParsed ?? [],
  };
}

function acceptsInput(node: PersistedCanvasNode): boolean {
  const { capabilities, parsedKeys } = requirementsOf(node);
  return capabilities.length > 0 || parsedKeys.length > 0;
}

function toCandidate(node: PersistedCanvasNode, handle: string, withOutcome: boolean): GroupConnectionCandidate {
  return {
    nodeId: node.id,
    handle,
    title: withOutcome ? `${node.data.title} · ${handle}` : node.data.title,
    kind: node.data.kind,
  };
}

function inputCandidates(query: CandidateQuery, members: PersistedCanvasNode[]): GroupConnectionCandidate[] {
  const { otherEnd, flatProvides, allEdges, group } = query;
  const memberIds = new Set(group.nodeIds);
  const hasInternalIncoming = (id: string) =>
    allEdges.some((e) => e.target === id && memberIds.has(e.source));

  const provided = otherEnd
    ? getOutcomeProvides(flatProvides, otherEnd.nodeId, otherEnd.handle)
    : null;

  return members
    .filter(acceptsInput)
    .filter((node) => !provided || isCompatible(provided, requirementsOf(node)))
    .sort((a, b) => Number(hasInternalIncoming(a.id)) - Number(hasInternalIncoming(b.id)))
    .map((node) => toCandidate(node, DEFAULT_TARGET_HANDLE, false));
}

function outputCandidates(query: CandidateQuery, members: PersistedCanvasNode[]): GroupConnectionCandidate[] {
  const { otherEnd, flatProvides, allNodes } = query;

  let required: ReturnType<typeof requirementsOf> | null = null;
  if (otherEnd) {
    const target = allNodes.find((n) => n.id === otherEnd.nodeId);
    if (!target || !acceptsInput(target)) return [];
    if (
      (target.data.requires ?? []).length > 0 &&
      otherEnd.handle &&
      otherEnd.handle !== DEFAULT_TARGET_HANDLE
    ) {
      return [];
    }
    required = requirementsOf(target);
  }

  return members.flatMap((node) =>
    (node.data.outcomes ?? [{ name: DEFAULT_OUTCOME }])
      .filter(
        (outcome) =>
          !required || isCompatible(getOutcomeProvides(flatProvides, node.id, outcome.name), required),
      )
      .map((outcome) => toCandidate(node, outcome.name, true)),
  );
}

/**
 * Which member steps of a collapsed group can take (input) or provide (output)
 * a connection from/to `otherEnd`. Compatibility is judged on the flat graph,
 * so a group with no boundary edges yet still offers its real steps.
 */
export function listGroupConnectionCandidates(query: CandidateQuery): GroupConnectionCandidate[] {
  const { side, group, groupHandleId, allNodes, allEdges } = query;
  const memberIds = new Set(group.nodeIds);
  const members = allNodes.filter((n) => memberIds.has(n.id) && isRealStep(n));

  const prefix = side === "input" ? GROUP_INPUT_HANDLE_PREFIX : GROUP_OUTPUT_HANDLE_PREFIX;
  if (groupHandleId?.startsWith(prefix)) {
    const ports = deriveGroupPorts(group.nodeIds, allEdges);
    const port = (side === "input" ? ports.inputs : ports.outputs).find(
      (p) => p.edgeId === groupHandleId.slice(prefix.length),
    );
    const pinned = port ? members.filter((n) => n.id === port.innerNodeId) : [];
    const all = side === "input" ? inputCandidates(query, pinned) : outputCandidates(query, pinned);
    return port && side === "output" ? all.filter((c) => c.handle === port.innerHandle) : all;
  }

  return side === "input" ? inputCandidates(query, members) : outputCandidates(query, members);
}
