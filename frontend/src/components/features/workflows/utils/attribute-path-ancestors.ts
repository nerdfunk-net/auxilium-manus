import type { PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";

/**
 * All node ids that can reach `nodeId` by following edges forward (i.e. every
 * node that is an ancestor of `nodeId` in the workflow graph). Used to
 * restrict the attribute-path picker/preview to steps whose output could
 * plausibly exist by the time execution reaches `nodeId` — a downstream step
 * can never be a source of data for an earlier step's config.
 *
 * Full reachability (not just the nearest producer per branch, unlike
 * `findUpstreamOutput`), visited-set guarded so a cycle can't loop forever.
 */
export function getAncestorNodeIds(
  nodeId: string,
  nodes: PersistedCanvasNode[],
  edges: WorkflowCanvasEdge[],
): Set<string> {
  const parents = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parents.get(edge.target) ?? [];
    list.push(edge.source);
    parents.set(edge.target, list);
  }

  const nodeIds = new Set(nodes.map((node) => node.id));
  const ancestors = new Set<string>();
  const queue = [...(parents.get(nodeId) ?? [])];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (ancestors.has(current) || !nodeIds.has(current)) {
      continue;
    }
    ancestors.add(current);
    queue.push(...(parents.get(current) ?? []));
  }

  return ancestors;
}
