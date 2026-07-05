import type { WorkflowOutcomeField } from "@/components/features/workflows/types/workflow-canvas";

export type UpdateAttributeMode = "fixed" | "regex";

export interface RegexFlags {
  case_insensitive: boolean;
  multiline: boolean;
  dotall: boolean;
}

export interface UpdateAttributeConfig {
  mode: UpdateAttributeMode;
  destination_path: string;
  fixed_value: string;
  source_path: string;
  pattern: string;
  destination_template: string;
  regex_flags: RegexFlags;
}

export const DEFAULT_UPDATE_ATTRIBUTE_CONFIG: UpdateAttributeConfig = {
  mode: "fixed",
  destination_path: "custom.location",
  fixed_value: "",
  source_path: "device.name",
  pattern: String.raw`^([^-]+)-`,
  destination_template: String.raw`DC-\1`,
  regex_flags: {
    case_insensitive: false,
    multiline: false,
    dotall: false,
  },
};

function parseRegexFlags(raw: unknown): RegexFlags {
  if (!raw || typeof raw !== "object") {
    return DEFAULT_UPDATE_ATTRIBUTE_CONFIG.regex_flags;
  }
  const flags = raw as Record<string, unknown>;
  return {
    case_insensitive: flags.case_insensitive === true,
    multiline: flags.multiline === true,
    dotall: flags.dotall === true,
  };
}

function parseMode(raw: unknown): UpdateAttributeMode {
  return raw === "regex" ? "regex" : "fixed";
}

export function parseUpdateAttributeConfig(
  config: Record<string, unknown>,
): UpdateAttributeConfig {
  return {
    mode: parseMode(config.mode),
    destination_path:
      typeof config.destination_path === "string" && config.destination_path.trim()
        ? config.destination_path.trim()
        : DEFAULT_UPDATE_ATTRIBUTE_CONFIG.destination_path,
    fixed_value:
      typeof config.fixed_value === "string"
        ? config.fixed_value
        : DEFAULT_UPDATE_ATTRIBUTE_CONFIG.fixed_value,
    source_path:
      typeof config.source_path === "string" && config.source_path.trim()
        ? config.source_path.trim()
        : DEFAULT_UPDATE_ATTRIBUTE_CONFIG.source_path,
    pattern:
      typeof config.pattern === "string"
        ? config.pattern
        : DEFAULT_UPDATE_ATTRIBUTE_CONFIG.pattern,
    destination_template:
      typeof config.destination_template === "string"
        ? config.destination_template
        : DEFAULT_UPDATE_ATTRIBUTE_CONFIG.destination_template,
    regex_flags: parseRegexFlags(config.regex_flags),
  };
}

export function buildUpdateAttributeConfig(
  config: Record<string, unknown>,
  patch: Partial<UpdateAttributeConfig> = {},
): Record<string, unknown> {
  const current = parseUpdateAttributeConfig(config);
  const next: UpdateAttributeConfig = {
    ...current,
    ...patch,
    regex_flags: {
      ...current.regex_flags,
      ...(patch.regex_flags ?? {}),
    },
  };
  return next as unknown as Record<string, unknown>;
}

export function deriveUpdateAttributeOutcomes(): WorkflowOutcomeField[] {
  return [{ name: "success" }];
}
