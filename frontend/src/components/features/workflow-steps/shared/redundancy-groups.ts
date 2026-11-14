/**
 * The ``redundancy_groups`` setting of the steps that write interfaces to Nautobot
 * (update-nautobot-device, add-to-nautobot): HSRP/VRRP groups of the interfaces.
 * Mirrors ``workflow_steps/common/redundancy_groups_config.py`` on the backend.
 */

export interface RedundancyGroupsConfig {
  enabled: boolean;
  /** Name schema of a NEW group: {next} = lowest free integer, {protocol} = e.g. "hsrp". */
  name_pattern: string;
  /** Nautobot status of a new group. */
  status: string;
}

export const DEFAULT_REDUNDANCY_GROUPS_CONFIG: RedundancyGroupsConfig = {
  enabled: false,
  name_pattern: "hsrp-{next}",
  status: "Active",
};

/** Statuses Nautobot offers for an interface redundancy group. */
export const REDUNDANCY_GROUP_STATUSES = [
  "Active",
  "Planned",
  "Staging",
  "Decommissioning",
  "Retired",
] as const;

/** The backend refuses a longer pattern (255 characters of a name, minus room for the number). */
export const REDUNDANCY_PATTERN_MAX_LENGTH = 249;

const NEXT_PLACEHOLDER = "{next}";
const PROTOCOL_PLACEHOLDER = "{protocol}";

/** Why a redundancy-group name pattern would be refused (null when fine). Mirrors the backend. */
export function redundancyPatternProblem(pattern: string): string | null {
  const text = pattern.trim();
  if (!text) return "Enter a name pattern, e.g. hsrp-{next}.";
  if (text.split(NEXT_PLACEHOLDER).length !== 2) {
    return `The pattern must contain ${NEXT_PLACEHOLDER} exactly once.`;
  }
  const literal = text.split(NEXT_PLACEHOLDER).join("").split(PROTOCOL_PLACEHOLDER).join("");
  if (literal.includes("{") || literal.includes("}")) {
    return `Only ${NEXT_PLACEHOLDER} and ${PROTOCOL_PLACEHOLDER} may be used in braces.`;
  }
  if (text.includes("/") || /[\u0000-\u001f]/.test(text)) {
    return "The pattern must not contain '/' or control characters.";
  }
  if (text.length > REDUNDANCY_PATTERN_MAX_LENGTH) {
    return `The pattern is too long (at most ${REDUNDANCY_PATTERN_MAX_LENGTH} characters).`;
  }
  return null;
}

/** The first names a pattern gives, for the hint under the input ("hsrp-1, hsrp-2, hsrp-3"). */
export function redundancyNameExamples(pattern: string): string {
  const base = pattern.trim().split(PROTOCOL_PLACEHOLDER).join("hsrp");
  return [1, 2, 3].map((n) => base.split(NEXT_PLACEHOLDER).join(String(n))).join(", ");
}

/** Read the saved ``redundancy_groups`` setting; absent or malformed gives the defaults. */
export function parseRedundancyGroupsConfig(raw: unknown): RedundancyGroupsConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return DEFAULT_REDUNDANCY_GROUPS_CONFIG;
  }
  const record = raw as Record<string, unknown>;
  const text = (value: unknown, fallback: string) =>
    typeof value === "string" && value.trim() ? value : fallback;
  return {
    enabled: record.enabled === true,
    name_pattern: text(record.name_pattern, DEFAULT_REDUNDANCY_GROUPS_CONFIG.name_pattern),
    status: text(record.status, DEFAULT_REDUNDANCY_GROUPS_CONFIG.status),
  };
}

/** What to save: trimmed, and off for any source but nautobot_origin (the backend refuses it). */
export function redundancyGroupsForSave(
  value: RedundancyGroupsConfig,
  source: string,
): RedundancyGroupsConfig {
  return {
    enabled: value.enabled && source === "nautobot_origin",
    name_pattern: value.name_pattern.trim(),
    status: value.status.trim() || DEFAULT_REDUNDANCY_GROUPS_CONFIG.status,
  };
}
