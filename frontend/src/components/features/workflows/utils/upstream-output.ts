import type { PluginDefinition } from "../types/plugin-registry";
import type { WorkflowCanvasEdge, WorkflowCanvasNode } from "../types/workflow-canvas";

export interface UpstreamOutput {
  contentSource: string;
  sourceNodeId: string;
  stepTitle: string;
  stepKind: string;
}

/**
 * Walk the edge graph backwards from `nodeId`, skipping pass-through steps
 * (those without a `primary_output` field), and return a descriptor for the
 * nearest content-producing upstream step.
 *
 * Returns null when no content producer is found, or when the first level of
 * producers found across parallel branches disagree on content type / node id.
 */
export function findUpstreamOutput(
  nodeId: string,
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  plugins: PluginDefinition[],
): UpstreamOutput | null {
  const nodesById = new Map(nodes.map((n) => [n.id, n]));
  const pluginsById = new Map(plugins.map((p) => [p.id, p]));

  // parent map: target nodeId → [source nodeId, ...]
  const parents = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parents.get(edge.target) ?? [];
    list.push(edge.source);
    parents.set(edge.target, list);
  }

  // BFS backwards; process the current frontier level-by-level so that
  // producers found on parallel branches at the same depth can be compared.
  let frontier: string[] = [nodeId];
  const visited = new Set<string>([nodeId]);

  while (frontier.length > 0) {
    const producers: UpstreamOutput[] = [];
    const nextFrontier: string[] = [];

    for (const current of frontier) {
      for (const parentId of parents.get(current) ?? []) {
        if (visited.has(parentId)) continue;
        visited.add(parentId);

        const parentNode = nodesById.get(parentId);
        if (!parentNode) continue;

        const plugin = pluginsById.get(parentNode.data.kind);
        if (plugin?.primary_output) {
          producers.push({
            contentSource: plugin.primary_output,
            sourceNodeId: parentId,
            stepTitle: parentNode.data.title?.trim() || parentId,
            stepKind: parentNode.data.kind,
          });
        } else {
          // pass-through step — keep walking
          nextFrontier.push(parentId);
        }
      }
    }

    if (producers.length === 0) {
      frontier = nextFrontier;
      continue;
    }

    if (producers.length === 1) return producers[0];

    // Multiple producers found at this depth — only unambiguous if they all
    // point to the same node and content type.
    const first = producers[0];
    const allAgree = producers.every(
      (p) =>
        p.contentSource === first.contentSource &&
        p.sourceNodeId === first.sourceNodeId,
    );
    return allAgree ? first : null;
  }

  return null;
}
