import type { WorkflowCanvasEdge } from "../types/workflow-canvas";

/** One edge crossing a group's boundary. */
export interface GroupPort {
  /** Real (unprojected) edge id. */
  edgeId: string;
  /** Member step the edge attaches to. */
  innerNodeId: string;
  /** Handle on the member step (target handle for inputs, source handle for outputs). */
  innerHandle: string;
  /** Step on the other side of the boundary. */
  outerNodeId: string;
}

export interface GroupPorts {
  inputs: GroupPort[];
  outputs: GroupPort[];
}

const DEFAULT_TARGET_HANDLE = "input";
const DEFAULT_SOURCE_HANDLE = "success";

/**
 * Derives a group's boundary ports from its membership and the authoritative
 * edge list. Ports are never stored — moving a step in or out of a group only
 * changes `nodeIds`, and the ports follow.
 */
export function deriveGroupPorts(
  nodeIds: readonly string[],
  edges: readonly WorkflowCanvasEdge[],
): GroupPorts {
  const members = new Set(nodeIds);
  const inputs: GroupPort[] = [];
  const outputs: GroupPort[] = [];

  for (const edge of edges) {
    const sourceInside = members.has(edge.source);
    const targetInside = members.has(edge.target);
    if (!sourceInside && targetInside) {
      inputs.push({
        edgeId: edge.id,
        innerNodeId: edge.target,
        innerHandle: edge.targetHandle ?? DEFAULT_TARGET_HANDLE,
        outerNodeId: edge.source,
      });
    } else if (sourceInside && !targetInside) {
      outputs.push({
        edgeId: edge.id,
        innerNodeId: edge.source,
        innerHandle: edge.sourceHandle ?? DEFAULT_SOURCE_HANDLE,
        outerNodeId: edge.target,
      });
    }
  }

  return { inputs, outputs };
}

export const GROUP_INPUT_HANDLE_PREFIX = "in:";
export const GROUP_OUTPUT_HANDLE_PREFIX = "out:";
