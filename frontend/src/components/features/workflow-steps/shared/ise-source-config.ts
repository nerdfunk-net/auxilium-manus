/** Config key for the Cisco ISE source reference stored on workflow step nodes. */
export const ISE_SOURCE_ID_KEY = "ise_source_id";

export function iseSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[ISE_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isIseSourceConfigured(config: Record<string, unknown>): boolean {
  return Boolean(iseSourceIdFromConfig(config));
}
