import type { WorkflowCanvasNode } from "../types/workflow-canvas";

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

function nodeWidth(node: WorkflowCanvasNode): number {
  return node.measured?.width ?? node.width ?? DEFAULT_NODE_WIDTH;
}

function nodeHeight(node: WorkflowCanvasNode): number {
  return node.measured?.height ?? node.height ?? DEFAULT_NODE_HEIGHT;
}

function selectedNodes(
  nodes: WorkflowCanvasNode[],
  nodeIds: string[],
): WorkflowCanvasNode[] {
  const idSet = new Set(nodeIds);
  return nodes.filter((node) => idSet.has(node.id));
}

export function alignCanvasNodes(
  nodes: WorkflowCanvasNode[],
  nodeIds: string[],
  alignment: NodeAlignment,
): WorkflowCanvasNode[] {
  const targets = selectedNodes(nodes, nodeIds);
  if (targets.length < 2) {
    return nodes;
  }

  const positions = targets.map((node) => ({
    id: node.id,
    x: node.position.x,
    y: node.position.y,
    width: nodeWidth(node),
    height: nodeHeight(node),
  }));

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
    return {
      ...node,
      position: nextPosition,
    };
  });
}
