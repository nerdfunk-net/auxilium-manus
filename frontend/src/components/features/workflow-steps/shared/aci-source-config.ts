/** Config key for the Cisco ACI source reference stored on workflow step nodes. */
export const ACI_SOURCE_ID_KEY = "aci_source_id";

export function aciSourceIdFromConfig(config: Record<string, unknown>): string {
  const raw = config[ACI_SOURCE_ID_KEY];
  if (typeof raw === "string" && raw.trim()) {
    return raw.trim();
  }
  return "";
}

export function isAciSourceConfigured(config: Record<string, unknown>): boolean {
  return Boolean(aciSourceIdFromConfig(config));
}
