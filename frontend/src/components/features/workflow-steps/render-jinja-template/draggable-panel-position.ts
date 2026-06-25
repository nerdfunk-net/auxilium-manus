/** Minimum pixels that must stay inside the viewport so a floating panel can be dragged back. */
export const DRAG_HANDLE_MIN_VISIBLE_PX = 56;

export function constrainFloatingPosition(
  position: { x: number; y: number },
  width: number,
  height: number,
) {
  if (typeof window === "undefined") {
    return position;
  }

  const minX = -(width - DRAG_HANDLE_MIN_VISIBLE_PX);
  const maxX = window.innerWidth - DRAG_HANDLE_MIN_VISIBLE_PX;
  const minY = -(height - DRAG_HANDLE_MIN_VISIBLE_PX);
  const maxY = window.innerHeight - DRAG_HANDLE_MIN_VISIBLE_PX;

  return {
    x: Math.min(Math.max(minX, position.x), maxX),
    y: Math.min(Math.max(minY, position.y), maxY),
  };
}
