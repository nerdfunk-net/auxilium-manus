import { z } from "zod";

import {
  CUSTOM_FIELD_PREFIX,
  IGNORE_TARGET,
  INTERFACE_NAME_TARGET,
  INTERFACE_PREFIX,
  isCustomFieldTarget,
  isKnownTarget,
  NAME_TARGET,
} from "../constants/nautobot-targets";

export interface DeviceMappingRule {
  source: string;
  target: string;
}

export const EMPTY_MAPPING: readonly DeviceMappingRule[] = [];

/** Mirrors the backend default used when no mapping is configured. */
export const DEFAULT_MAPPING: readonly DeviceMappingRule[] = [
  { source: "name", target: "name" },
  { source: "primary_ip4", target: "primary_ip4.address" },
  { source: "network_driver", target: "platform.network_driver" },
];

const ruleSchema = z.object({
  source: z.string().trim().min(1, "File key is required"),
  target: z
    .string()
    .refine((value) => value !== "", "Select a Nautobot attribute")
    .refine(
      (value) => value !== CUSTOM_FIELD_PREFIX,
      "Enter a custom field name",
    )
    .refine(
      (value) => !isCustomFieldTarget(value) || isKnownTarget(value),
      "Custom field names may only contain letters, digits and underscores",
    )
    .refine(isKnownTarget, "Select a Nautobot attribute"),
});

export function mappingFromConfig(config: Record<string, unknown>): DeviceMappingRule[] {
  const raw = config.device_mapping;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.flatMap((row) => {
    const parsed = z.object({ source: z.string(), target: z.string() }).safeParse(row);
    return parsed.success ? [parsed.data] : [];
  });
}

/** Returns one error message per row index (and `form` for mapping-wide problems). */
export interface MappingErrors {
  rows: Record<number, string>;
  form: string | null;
}

export function validateMapping(rules: readonly DeviceMappingRule[]): MappingErrors {
  const errors: MappingErrors = { rows: {}, form: null };
  const seen = new Set<string>();
  rules.forEach((rule, index) => {
    const parsed = ruleSchema.safeParse(rule);
    if (!parsed.success) {
      errors.rows[index] = parsed.error.issues[0]?.message ?? "Invalid row";
    } else if (rule.target !== IGNORE_TARGET && seen.has(rule.target)) {
      errors.rows[index] = "Each Nautobot attribute can only be mapped once";
    }
    seen.add(rule.target);
  });
  if (rules.length > 0 && !rules.some((rule) => rule.target === NAME_TARGET)) {
    errors.form = "A file key must be mapped to “Device name”.";
  }
  const usesInterface = rules.some((rule) => rule.target.startsWith(INTERFACE_PREFIX));
  if (usesInterface && !rules.some((rule) => rule.target === INTERFACE_NAME_TARGET)) {
    errors.form ??= "Interface attributes need a column mapped to “Interface name”.";
  }
  return errors;
}

export function hasMappingErrors(errors: MappingErrors): boolean {
  return errors.form !== null || Object.keys(errors.rows).length > 0;
}

export function cleanMapping(rules: readonly DeviceMappingRule[]): DeviceMappingRule[] {
  return rules.map((rule) => ({ source: rule.source.trim(), target: rule.target }));
}

/** Common column names → Nautobot target, used to pre-fill the mapping from a file's keys. */
const KEY_ALIASES: Readonly<Record<string, string>> = {
  name: "name",
  device_name: "name",
  hostname: "hostname",
  serial: "serial",
  serial_number: "serial",
  asset_tag: "asset_tag",
  position: "position",
  face: "face",
  ip: "primary_ip4.address",
  ip_address: "primary_ip4.address",
  primary_ip: "primary_ip4.address",
  primary_ip4: "primary_ip4.address",
  mgmt_ip: "primary_ip4.address",
  role: "role.name",
  device_type: "device_type.model",
  model: "device_type.model",
  manufacturer: "device_type.manufacturer.name",
  vendor: "device_type.manufacturer.name",
  platform: "platform.name",
  network_driver: "platform.network_driver",
  driver: "platform.network_driver",
  location: "location.name",
  site: "location.name",
  location_description: "location.description",
  parent_location: "location.parent.name",
  status: "status.name",
  interface: "interfaces.name",
  interface_name: "interfaces.name",
  interface_description: "interfaces.description",
  interface_type: "interfaces.type",
  interface_mac: "interfaces.mac_address",
  interface_mac_address: "interfaces.mac_address",
  interface_mtu: "interfaces.mtu",
  interface_status: "interfaces.status.name",
  interface_ip: "interfaces.ip_addresses.address",
  interface_ip_address: "interfaces.ip_addresses.address",
};

/** Best-guess target for a file key; `IGNORE_TARGET` when nothing matches. */
export function suggestTarget(key: string): string {
  const normalized = key.trim().toLowerCase();
  if (normalized.startsWith("cf_")) {
    const custom = `${CUSTOM_FIELD_PREFIX}${key.trim().slice(3)}`;
    return key.trim().length > 3 && isKnownTarget(custom) ? custom : IGNORE_TARGET;
  }
  const alias = KEY_ALIASES[normalized];
  if (alias) {
    return alias;
  }
  return isKnownTarget(key.trim()) ? key.trim() : IGNORE_TARGET;
}

function sameMapping(a: readonly DeviceMappingRule[], b: readonly DeviceMappingRule[]): boolean {
  return a.length === b.length && a.every((rule, i) => rule.source === b[i].source && rule.target === b[i].target);
}

/**
 * Rows for every file key. Keys already mapped keep their row; the untouched default
 * mapping is replaced; a suggested target that is already taken falls back to Ignore.
 */
export function mappingFromKeys(
  existing: readonly DeviceMappingRule[],
  keys: readonly string[],
): DeviceMappingRule[] {
  const base = sameMapping(existing, DEFAULT_MAPPING) ? [] : [...existing];
  const usedSources = new Set(base.map((rule) => rule.source));
  const usedTargets = new Set(base.map((rule) => rule.target));
  const added: DeviceMappingRule[] = [];
  for (const key of keys) {
    // Nested keys (a.b) are offered for picking but a row per column is what users expect.
    if (key.includes(".") || usedSources.has(key)) {
      continue;
    }
    const suggested = suggestTarget(key);
    const target =
      suggested !== IGNORE_TARGET && usedTargets.has(suggested) ? IGNORE_TARGET : suggested;
    usedSources.add(key);
    usedTargets.add(target);
    added.push({ source: key, target });
  }
  return [...base, ...added];
}
