export const MIN_LOOKBACK_HOURS = 1;
export const MAX_LOOKBACK_HOURS = 168;
export const DEFAULT_LOOKBACK_HOURS = 24;

/**
 * Whole hours inside the backend range (backend/workflow_steps/get_catalyst_center_client_data):
 * anything that is not a number falls back to the default.
 */
export function clampLookbackHours(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_LOOKBACK_HOURS, Math.max(MIN_LOOKBACK_HOURS, parsed))
    : DEFAULT_LOOKBACK_HOURS;
}

export function readLookbackHours(config: Record<string, unknown>): number {
  const value = config.lookback_hours;
  // Clamp like the control does on change: a saved 0 or 9999 would fail the whole step.
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(MAX_LOOKBACK_HOURS, Math.max(MIN_LOOKBACK_HOURS, Math.trunc(value)))
    : DEFAULT_LOOKBACK_HOURS;
}
