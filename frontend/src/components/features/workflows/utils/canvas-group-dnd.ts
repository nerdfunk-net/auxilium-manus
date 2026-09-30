import type { ProjectedCanvasNode } from "../types/workflow-canvas";
import { isGroupCanvasNode } from "./canvas-group-projection";

interface Point {
  x: number;
  y: number;
}

interface ClientRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

const EMPTY_IDS: ReadonlySet<string> = new Set();

/**
 * Finds the collapsed group node under a flow-space point. Later nodes render
 * on top, so the last match wins. Groups in `excludeNodeIds` (e.g. being
 * dragged themselves) never match.
 */
export function findGroupNodeAtPoint(
  point: Point,
  nodes: readonly ProjectedCanvasNode[],
  excludeNodeIds: ReadonlySet<string> = EMPTY_IDS,
): string | null {
  let hit: string | null = null;
  for (const node of nodes) {
    if (!isGroupCanvasNode(node) || excludeNodeIds.has(node.id)) continue;
    const width = node.width ?? node.measured?.width ?? 0;
    const height = node.height ?? node.measured?.height ?? 0;
    if (
      point.x >= node.position.x &&
      point.x <= node.position.x + width &&
      point.y >= node.position.y &&
      point.y <= node.position.y + height
    ) {
      hit = node.data.groupId;
    }
  }
  return hit;
}

/**
 * Ids among dragged nodes that may change group membership: real steps and
 * labels. Synthetic group nodes, backgrounds and steps parented to a
 * background are excluded (same rules as the side-panel "Move to group").
 */
export function draggableStepIds(draggedNodes: readonly ProjectedCanvasNode[]): string[] {
  return draggedNodes
    .filter(
      (node) =>
        !isGroupCanvasNode(node) && node.type !== "backgroundNode" && !node.parentId,
    )
    .map((node) => node.id);
}

export function isPointInClientRect(clientX: number, clientY: number, rect: ClientRect): boolean {
  return (
    clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom
  );
}
