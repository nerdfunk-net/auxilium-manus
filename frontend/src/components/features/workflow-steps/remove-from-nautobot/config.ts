export const DEVICE_ID_KEY = "device_id";
export const REMOVE_IP_ADDRESSES_KEY = "remove_ip_addresses";

/** Same expression the backend config.py starts a new step with. */
export const DEFAULT_DEVICE_ID = "{device.id}";

export const DEVICE_ID_MISSING_PROBLEM = "device_id is not configured";

/** The stored flag is a real boolean, but older rows may still carry its string spelling. */
export function removeIpAddressesFromConfig(config: Record<string, unknown>): boolean {
  const value = config[REMOVE_IP_ADDRESSES_KEY];
  if (typeof value === "string") return ["true", "1", "yes", "on"].includes(value.trim().toLowerCase());
  return value === true;
}

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const id = config[DEVICE_ID_KEY];
  return typeof id === "string" && id.trim() ? [] : [DEVICE_ID_MISSING_PROBLEM];
}
