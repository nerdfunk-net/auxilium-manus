/** Bounds for the resizable VARIABLES panel in the template editor. */
export const MIN_VARIABLES_WIDTH = 260;
export const MAX_VARIABLES_WIDTH = 720;
export const DEFAULT_VARIABLES_WIDTH = 340;

/** Clamp a pixel width into the allowed VARIABLES-panel range. */
export function clampPanelWidth(px: number): number {
  if (!Number.isFinite(px)) {
    return DEFAULT_VARIABLES_WIDTH;
  }
  return Math.min(
    MAX_VARIABLES_WIDTH,
    Math.max(MIN_VARIABLES_WIDTH, Math.round(px)),
  );
}
