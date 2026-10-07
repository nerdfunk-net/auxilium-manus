import { z } from "zod";

import { isKnownTarget, NAME_TARGET } from "../constants/nautobot-targets";

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
  target: z.string().refine(isKnownTarget, "Select a Nautobot attribute"),
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
    } else if (seen.has(rule.target)) {
      errors.rows[index] = "Each Nautobot attribute can only be mapped once";
    }
    seen.add(rule.target);
  });
  if (rules.length > 0 && !rules.some((rule) => rule.target === NAME_TARGET)) {
    errors.form = "A file key must be mapped to “Device name”.";
  }
  return errors;
}

export function hasMappingErrors(errors: MappingErrors): boolean {
  return errors.form !== null || Object.keys(errors.rows).length > 0;
}

export function cleanMapping(rules: readonly DeviceMappingRule[]): DeviceMappingRule[] {
  return rules.map((rule) => ({ source: rule.source.trim(), target: rule.target }));
}
