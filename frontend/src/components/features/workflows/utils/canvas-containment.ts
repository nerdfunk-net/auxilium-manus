import type { PersistedCanvasNode } from "../types/workflow-canvas";

interface Point {
  x: number;
  y: number;
}

interface Rect extends Point {
  width: number;
  height: number;
}

function nodeSize(node: PersistedCanvasNode): { width: number; height: number } {
  return {
    width: node.width ?? node.measured?.width ?? 0,
    height: node.height ?? node.measured?.height ?? 0,
  };
}

export function toAbsolutePosition(relative: Point, parent: Point): Point {
  return { x: relative.x + parent.x, y: relative.y + parent.y };
}

export function toRelativePosition(absolute: Point, parent: Point): Point {
  return { x: absolute.x - parent.x, y: absolute.y - parent.y };
}

/**
 * Backgrounds are never themselves nested (single-level containment only), so
 * a background's own `position` is always in absolute canvas coordinates.
 */
function getBackgroundAbsolutePosition(
  backgroundId: string,
  allNodes: PersistedCanvasNode[],
): Point | undefined {
  return allNodes.find((n) => n.id === backgroundId && n.type === "backgroundNode")
    ?.position;
}

function rectCenter(rect: Rect): Point {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

function rectContainsPoint(rect: Rect, point: Point): boolean {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

/**
 * Finds which background (if any) a node's absolute-position center point
 * falls inside. If multiple backgrounds overlap at that point, the smallest
 * (most specific) one wins.
 */
export function findContainingBackground(
  absolutePosition: Point,
  size: { width: number; height: number },
  allNodes: PersistedCanvasNode[],
  excludeNodeId: string,
): PersistedCanvasNode | undefined {
  const center = rectCenter({ ...absolutePosition, ...size });
  let best: PersistedCanvasNode | undefined;
  let bestArea = Infinity;

  for (const candidate of allNodes) {
    if (candidate.type !== "backgroundNode" || candidate.id === excludeNodeId) continue;
    const rect: Rect = { ...candidate.position, ...nodeSize(candidate) };
    if (!rectContainsPoint(rect, center)) continue;
    const area = rect.width * rect.height;
    if (area < bestArea) {
      bestArea = area;
      best = candidate;
    }
  }

  return best;
}

export interface ContainmentResult {
  parentId: string | undefined;
  position: Point;
}

/**
 * Re-evaluates a node's background containment after it has moved.
 *
 * `node` must still carry its *previous* `parentId` (if any) and its *new*
 * `position` expressed relative to that previous parent (or absolute, if
 * none) — i.e. the raw merged node React Flow hands back from a position
 * change, before we've touched `parentId` ourselves.
 *
 * Deliberately does not set React Flow's `extent: 'parent'` — that clamps
 * drag movement to stay inside the parent, which would make it impossible to
 * ever drag a step back out to detach it. Containment here is purely our own
 * center-point overlap check, re-evaluated on every drag-end.
 */
export function resolveContainment(
  node: PersistedCanvasNode,
  allNodes: PersistedCanvasNode[],
): ContainmentResult {
  const previousParentId = node.parentId;
  const absolutePosition = previousParentId
    ? toAbsolutePosition(
        node.position,
        getBackgroundAbsolutePosition(previousParentId, allNodes) ?? { x: 0, y: 0 },
      )
    : node.position;

  const nextParent = findContainingBackground(
    absolutePosition,
    nodeSize(node),
    allNodes,
    node.id,
  );

  if (!nextParent) {
    return { parentId: undefined, position: absolutePosition };
  }

  return {
    parentId: nextParent.id,
    position: toRelativePosition(absolutePosition, nextParent.position),
  };
}
