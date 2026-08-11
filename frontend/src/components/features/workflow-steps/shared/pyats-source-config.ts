/** Config key for the pyATS source reference stored on workflow step nodes. */
export const PYATS_SOURCE_ID_KEY = "pyats_source_id";

export function pyatsSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[PYATS_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isPyatsSourceConfigured(config: Record<string, unknown>): boolean {
  return Boolean(pyatsSourceIdFromConfig(config));
}
