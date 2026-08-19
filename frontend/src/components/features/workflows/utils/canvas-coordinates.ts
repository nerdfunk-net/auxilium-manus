import type { ProjectedCanvasNode } from "../types/workflow-canvas";

// Fallback used when a node hasn't been measured by React Flow yet (e.g. it
// was just added, or is being processed before its first render/measure
// pass). Matches the default workflowNode footprint (`w-80 h-32`).
const DEFAULT_NODE_WIDTH = 224;
const DEFAULT_NODE_HEIGHT = 112;

export function nodeWidth(node: ProjectedCanvasNode): number {
  return node.measured?.width ?? node.width ?? DEFAULT_NODE_WIDTH;
}

export function nodeHeight(node: ProjectedCanvasNode): number {
  return node.measured?.height ?? node.height ?? DEFAULT_NODE_HEIGHT;
}

/**
 * A step parented to a background node (single-level nesting only, see
 * canvas-containment.ts) stores `position` relative to that parent, while every
 * other node stores absolute canvas position. Operating on a mix of the two
 * requires a shared coordinate space, so this resolves each target's parent
 * offset (zero when un-parented) up front so it can be undone after computing
 * new absolute positions.
 */
export function parentOffset(
  node: ProjectedCanvasNode,
  nodesById: Map<string, ProjectedCanvasNode>,
): { x: number; y: number } {
  const parentId = node.parentId;
  if (!parentId) {
    return { x: 0, y: 0 };
  }
  const parent = nodesById.get(parentId);
  return parent ? { x: parent.position.x, y: parent.position.y } : { x: 0, y: 0 };
}
