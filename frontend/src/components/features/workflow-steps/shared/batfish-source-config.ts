/** Config key for the Batfish source reference stored on workflow step nodes. */
export const BATFISH_SOURCE_ID_KEY = "batfish_source_id";

export function batfishSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[BATFISH_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isBatfishSourceConfigured(config: Record<string, unknown>): boolean {
  return Boolean(batfishSourceIdFromConfig(config));
}
