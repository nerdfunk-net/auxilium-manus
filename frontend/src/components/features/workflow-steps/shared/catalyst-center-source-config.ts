/** Config key for the Cisco Catalyst Center source reference stored on workflow step nodes. */
export const CATALYST_CENTER_SOURCE_ID_KEY = "catalyst_center_source_id";

export function catalystCenterSourceIdFromConfig(
  config: Record<string, unknown>,
): string {
  const raw = config[CATALYST_CENTER_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isCatalystCenterSourceConfigured(
  config: Record<string, unknown>,
): boolean {
  return Boolean(catalystCenterSourceIdFromConfig(config));
}
