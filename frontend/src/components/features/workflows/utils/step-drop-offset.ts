import { FUNNEL_KIND } from "../types/workflow-canvas";

export interface FlowPoint {
  x: number;
  y: number;
}

// Half the fixed node footprint (w-80 h-32), used to center a dropped step on the pointer.
const NODE_DROP_OFFSET: FlowPoint = { x: 160, y: 64 };
const LABEL_DROP_OFFSET: FlowPoint = { x: 100, y: 20 };
const BACKGROUND_DROP_OFFSET: FlowPoint = { x: 240, y: 160 };
// Half the funnel node's footprint (size-10 = 2.5rem = 40px).
const FUNNEL_DROP_OFFSET: FlowPoint = { x: 20, y: 20 };

/** Offset from the pointer to the node's top-left corner, so the node is centered on the pointer. */
export function getDropOffset(kind: string): FlowPoint {
  if (kind === "label") return LABEL_DROP_OFFSET;
  if (kind === "background") return BACKGROUND_DROP_OFFSET;
  if (kind === FUNNEL_KIND) return FUNNEL_DROP_OFFSET;
  return NODE_DROP_OFFSET;
}

/** Converts the stored flow-space pointer position into the top-left position for a step of `kind`. */
export function toDropPosition(pointer: FlowPoint, kind: string): FlowPoint {
  const offset = getDropOffset(kind);
  return { x: pointer.x - offset.x, y: pointer.y - offset.y };
}
