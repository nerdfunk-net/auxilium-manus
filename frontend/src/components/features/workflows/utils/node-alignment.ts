import type { ProjectedCanvasNode } from "../types/workflow-canvas";

const DEFAULT_NODE_WIDTH = 224;
const DEFAULT_NODE_HEIGHT = 112;

export type NodeAlignment =
  | "align-left"
  | "align-right"
  | "align-top"
  | "align-bottom"
  | "align-center-horizontal"
  | "align-center-vertical"
  | "distribute-horizontal"
  | "distribute-vertical";

function nodeWidth(node: ProjectedCanvasNode): number {
  return node.measured?.width ?? node.width ?? DEFAULT_NODE_WIDTH;
}

function nodeHeight(node: ProjectedCanvasNode): number {
  return node.measured?.height ?? node.height ?? DEFAULT_NODE_HEIGHT;
}

function selectedNodes(
  nodes: ProjectedCanvasNode[],
  nodeIds: string[],
): ProjectedCanvasNode[] {
  const idSet = new Set(nodeIds);
  return nodes.filter((node) => idSet.has(node.id));
}

/**
 * A step parented to a background node (single-level nesting only, see
 * canvas-containment.ts) stores `position` relative to that parent, while every
 * other node stores absolute canvas position. Aligning a mix of the two
 * requires a shared coordinate space, so this resolves each target's parent
 * offset (zero when un-parented) up front and undoes it after computing the
 * new absolute positions.
 */
function parentOffset(
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

export function alignCanvasNodes(
  nodes: ProjectedCanvasNode[],
  nodeIds: string[],
  alignment: NodeAlignment,
): ProjectedCanvasNode[] {
  const targets = selectedNodes(nodes, nodeIds);
  if (targets.length < 2) {
    return nodes;
  }

  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const offsetById = new Map(
    targets.map((node) => [node.id, parentOffset(node, nodesById)]),
  );

  // Absolute (canvas-space) positions, so parented and un-parented nodes align correctly.
  const positions = targets.map((node) => {
    const offset = offsetById.get(node.id)!;
    return {
      id: node.id,
      x: node.position.x + offset.x,
      y: node.position.y + offset.y,
      width: nodeWidth(node),
      height: nodeHeight(node),
    };
  });

  const nextPositions = new Map<string, { x: number; y: number }>();

  switch (alignment) {
    case "align-left": {
      const minX = Math.min(...positions.map((item) => item.x));
      for (const item of positions) {
        nextPositions.set(item.id, { x: minX, y: item.y });
      }
      break;
    }
    case "align-right": {
      const maxRight = Math.max(...positions.map((item) => item.x + item.width));
      for (const item of positions) {
        nextPositions.set(item.id, { x: maxRight - item.width, y: item.y });
      }
      break;
    }
    case "align-top": {
      const minY = Math.min(...positions.map((item) => item.y));
      for (const item of positions) {
        nextPositions.set(item.id, { x: item.x, y: minY });
      }
      break;
    }
    case "align-bottom": {
      const maxBottom = Math.max(...positions.map((item) => item.y + item.height));
      for (const item of positions) {
        nextPositions.set(item.id, { x: item.x, y: maxBottom - item.height });
      }
      break;
    }
    case "align-center-horizontal": {
      const centers = positions.map((item) => item.x + item.width / 2);
      const avgCenter = centers.reduce((sum, value) => sum + value, 0) / centers.length;
      for (const item of positions) {
        nextPositions.set(item.id, { x: avgCenter - item.width / 2, y: item.y });
      }
      break;
    }
    case "align-center-vertical": {
      const centers = positions.map((item) => item.y + item.height / 2);
      const avgCenter = centers.reduce((sum, value) => sum + value, 0) / centers.length;
      for (const item of positions) {
        nextPositions.set(item.id, { x: item.x, y: avgCenter - item.height / 2 });
      }
      break;
    }
    case "distribute-horizontal": {
      if (positions.length < 3) {
        return nodes;
      }
      const sorted = [...positions].sort((left, right) => left.x - right.x);
      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      const span = last.x - first.x;
      const step = span / (sorted.length - 1);
      sorted.forEach((item, index) => {
        nextPositions.set(item.id, { x: first.x + step * index, y: item.y });
      });
      break;
    }
    case "distribute-vertical": {
      if (positions.length < 3) {
        return nodes;
      }
      const sorted = [...positions].sort((left, right) => left.y - right.y);
      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      const span = last.y - first.y;
      const step = span / (sorted.length - 1);
      sorted.forEach((item, index) => {
        nextPositions.set(item.id, { x: item.x, y: first.y + step * index });
      });
      break;
    }
  }

  if (nextPositions.size === 0) {
    return nodes;
  }

  return nodes.map((node) => {
    const nextPosition = nextPositions.get(node.id);
    if (!nextPosition) {
      return node;
    }
    // Undo the parent offset applied above, converting back to the node's own coordinate space.
    const offset = offsetById.get(node.id) ?? { x: 0, y: 0 };
    return {
      ...node,
      position: { x: nextPosition.x - offset.x, y: nextPosition.y - offset.y },
    };
  });
}
