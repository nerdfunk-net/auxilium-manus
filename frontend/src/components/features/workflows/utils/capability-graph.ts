import type { Capability } from "@/lib/capability-types";

import type {
  ProjectedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";

export interface CapabilityState {
  capabilities: Set<Capability>;
  parsedKeys: Set<string>;
}

export interface OutcomeProvides {
  capabilities: Capability[];
  parsedKeys: string[];
}

function emptyState(): CapabilityState {
  return { capabilities: new Set(), parsedKeys: new Set() };
}

function applyStep(
  input: CapabilityState,
  node: ProjectedCanvasNode,
): CapabilityState {
  const produces = node.data.produces ?? [];
  const producesParsed = node.data.producesParsed ?? [];
  const consumes = node.data.consumes ?? [];

  const capabilities = new Set(input.capabilities);
  for (const cap of produces) {
    capabilities.add(cap);
  }
  for (const cap of consumes) {
    capabilities.delete(cap);
  }

  const parsedKeys = new Set(input.parsedKeys);
  for (const key of producesParsed) {
    parsedKeys.add(key);
  }

  return { capabilities, parsedKeys };
}

function intersectStates(states: CapabilityState[]): CapabilityState {
  if (states.length === 0) {
    return emptyState();
  }

  const capabilities = new Set(states[0].capabilities);
  const parsedKeys = new Set(states[0].parsedKeys);

  for (const state of states.slice(1)) {
    for (const cap of capabilities) {
      if (!state.capabilities.has(cap)) {
        capabilities.delete(cap);
      }
    }
    for (const key of parsedKeys) {
      if (!state.parsedKeys.has(key)) {
        parsedKeys.delete(key);
      }
    }
  }

  return { capabilities, parsedKeys };
}

function toProvides(state: CapabilityState): OutcomeProvides {
  return {
    capabilities: Array.from(state.capabilities),
    parsedKeys: Array.from(state.parsedKeys),
  };
}

/**
 * Compute transitive capability guarantees per node outcome handle for canvas validation.
 */
export function computeOutcomeProvides(
  nodes: ProjectedCanvasNode[],
  edges: WorkflowCanvasEdge[],
): Map<string, OutcomeProvides> {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, WorkflowCanvasEdge[]>();
  for (const edge of edges) {
    const list = incoming.get(edge.target) ?? [];
    list.push(edge);
    incoming.set(edge.target, list);
  }

  const inDegree = new Map<string, number>();
  for (const node of nodes) {
    inDegree.set(node.id, 0);
  }
  for (const edge of edges) {
    if (inDegree.has(edge.target)) {
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    }
  }

  const queue = nodes.filter((node) => (inDegree.get(node.id) ?? 0) === 0).map((n) => n.id);
  const order: string[] = [];
  const dependents = new Map<string, string[]>();
  for (const edge of edges) {
    const list = dependents.get(edge.source) ?? [];
    list.push(edge.target);
    dependents.set(edge.source, list);
  }

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    order.push(nodeId);
    for (const dep of dependents.get(nodeId) ?? []) {
      const next = (inDegree.get(dep) ?? 0) - 1;
      inDegree.set(dep, next);
      if (next === 0) {
        queue.push(dep);
      }
    }
  }

  const inputStateByNode = new Map<string, CapabilityState>();
  const outcomeProvides = new Map<string, OutcomeProvides>();

  for (const nodeId of order) {
    const node = nodesById.get(nodeId);
    if (!node) continue;

    const parentEdges = incoming.get(nodeId) ?? [];
    let inputState = emptyState();
    if (parentEdges.length > 0) {
      const parentStates = parentEdges.map((edge) => {
        const handle = edge.sourceHandle ?? "success";
        const key = `${edge.source}:${handle}`;
        const provides = outcomeProvides.get(key);
        return {
          capabilities: new Set(provides?.capabilities ?? []),
          parsedKeys: new Set(provides?.parsedKeys ?? []),
        };
      });
      inputState = intersectStates(parentStates);
    }

    inputStateByNode.set(nodeId, inputState);
    const outputState = applyStep(inputState, node);

    const outcomes = node.data.outcomes ?? [];
    if (outcomes.length === 0) {
      outcomeProvides.set(`${nodeId}:success`, toProvides(outputState));
      continue;
    }

    for (const outcome of outcomes) {
      outcomeProvides.set(`${nodeId}:${outcome.name}`, toProvides(outputState));
    }
  }

  return outcomeProvides;
}

export function getOutcomeProvides(
  outcomeProvides: Map<string, OutcomeProvides>,
  nodeId: string,
  handle: string | null | undefined,
): OutcomeProvides {
  const key = `${nodeId}:${handle ?? "success"}`;
  return outcomeProvides.get(key) ?? { capabilities: [], parsedKeys: [] };
}
