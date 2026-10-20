export const IP_ADDRESS_KEY = "ip_address";
export const NAMESPACE_KEY = "namespace";
export const STATUS_KEY = "status";
export const CREATE_PREFIX_KEY = "create_prefix";
export const DEFAULT_MASK_KEY = "default_mask_length";
export const DESCRIPTION_KEY = "description";
export const DNS_NAME_KEY = "dns_name";
export const RESULT_ATTRIBUTE_KEY = "result_attribute";
export const INTERFACE_KEY = "interface_name";
export const SET_PRIMARY_KEY = "set_primary";

export const DEFAULT_NAMESPACE = "Global";
export const DEFAULT_STATUS = "Active";

/**
 * New config with a number input's text applied. A whole number is stored as a number;
 * anything else (an empty box while typing) is kept as typed so the field stays editable.
 */
export function withNumberText(
  config: Record<string, unknown>,
  key: string,
  text: string,
): Record<string, unknown> {
  const trimmed = text.trim();
  return { ...config, [key]: /^-?\d+$/.test(trimmed) ? Number(trimmed) : text };
}

/** True for an empty box (use the default) or a whole number within 1-128. */
export function isValidMaskText(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return true;
  if (!/^\d+$/.test(trimmed)) return false;
  const value = Number(trimmed);
  return value >= 1 && value <= 128;
}

/** The configuration problems the panel shows as warnings (empty = complete). */
export function configProblems(config: Record<string, unknown>): string[] {
  const text = (key: string) =>
    typeof config[key] === "string" ? (config[key] as string).trim() : "";
  const problems: string[] = [];
  if (!text(IP_ADDRESS_KEY)) problems.push("ip_address is not configured");
  if (config[SET_PRIMARY_KEY] === true && !text(INTERFACE_KEY)) {
    problems.push("set_primary needs interface_name");
  }
  return problems;
}
