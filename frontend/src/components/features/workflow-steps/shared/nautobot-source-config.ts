/** Config key for the Nautobot source reference stored on workflow step nodes. */
export const NAUTOBOT_SOURCE_ID_KEY = "nautobot_source_id";

export function nautobotSourceIdFromConfig(
  config: Record<string, unknown>,
): string {
  const raw = config[NAUTOBOT_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim().toLowerCase();
  }
  return "";
}

export function isNautobotSourceConfigured(
  config: Record<string, unknown>,
): boolean {
  return Boolean(nautobotSourceIdFromConfig(config));
}
