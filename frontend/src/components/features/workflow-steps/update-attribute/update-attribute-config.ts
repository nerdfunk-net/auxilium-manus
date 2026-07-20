import type { WorkflowOutcomeField } from "@/components/features/workflows/types/workflow-canvas";

export type UpdateAttributeMode = "fixed" | "regex";

export interface RegexFlags {
  case_insensitive: boolean;
  multiline: boolean;
  dotall: boolean;
}

export interface AttributeUpdate {
  id: string;
  mode: UpdateAttributeMode;
  destination_path: string;
  fixed_value: string;
  source_path: string;
  pattern: string;
  destination_template: string;
  regex_flags: RegexFlags;
}

export interface UpdateAttributeConfig {
  attributes: AttributeUpdate[];
}

export const DEFAULT_REGEX_FLAGS: RegexFlags = {
  case_insensitive: false,
  multiline: false,
  dotall: false,
};

export const DEFAULT_ATTRIBUTE_UPDATE_FIELDS: Omit<AttributeUpdate, "id"> = {
  mode: "fixed",
  destination_path: "custom.location",
  fixed_value: "",
  source_path: "device.name",
  pattern: String.raw`^([^-]+)-`,
  destination_template: String.raw`DC-\1`,
  regex_flags: DEFAULT_REGEX_FLAGS,
};

export const DEFAULT_UPDATE_ATTRIBUTE_CONFIG: UpdateAttributeConfig = {
  attributes: [],
};

const EMPTY_ATTRIBUTES: AttributeUpdate[] = [];

function parseRegexFlags(raw: unknown): RegexFlags {
  if (!raw || typeof raw !== "object") {
    return DEFAULT_REGEX_FLAGS;
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

function newAttributeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `attr-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function createAttributeUpdate(
  patch: Partial<Omit<AttributeUpdate, "id">> = {},
): AttributeUpdate {
  return {
    id: newAttributeId(),
    ...DEFAULT_ATTRIBUTE_UPDATE_FIELDS,
    ...patch,
    regex_flags: {
      ...DEFAULT_REGEX_FLAGS,
      ...(patch.regex_flags ?? {}),
    },
  };
}

function parseAttributeUpdate(raw: unknown): AttributeUpdate | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const item = raw as Record<string, unknown>;
  return {
    id: typeof item.id === "string" && item.id.trim() ? item.id.trim() : newAttributeId(),
    mode: parseMode(item.mode),
    destination_path:
      typeof item.destination_path === "string" && item.destination_path.trim()
        ? item.destination_path.trim()
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.destination_path,
    fixed_value:
      typeof item.fixed_value === "string"
        ? item.fixed_value
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.fixed_value,
    source_path:
      typeof item.source_path === "string" && item.source_path.trim()
        ? item.source_path.trim()
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.source_path,
    pattern:
      typeof item.pattern === "string"
        ? item.pattern
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.pattern,
    destination_template:
      typeof item.destination_template === "string"
        ? item.destination_template
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.destination_template,
    regex_flags: parseRegexFlags(item.regex_flags),
  };
}

function parseLegacyAttribute(config: Record<string, unknown>): AttributeUpdate | null {
  const hasLegacyFields =
    typeof config.mode === "string" ||
    typeof config.destination_path === "string" ||
    typeof config.fixed_value === "string" ||
    typeof config.source_path === "string" ||
    typeof config.pattern === "string";
  if (!hasLegacyFields) {
    return null;
  }
  return {
    id: "legacy",
    mode: parseMode(config.mode),
    destination_path:
      typeof config.destination_path === "string" && config.destination_path.trim()
        ? config.destination_path.trim()
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.destination_path,
    fixed_value:
      typeof config.fixed_value === "string"
        ? config.fixed_value
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.fixed_value,
    source_path:
      typeof config.source_path === "string" && config.source_path.trim()
        ? config.source_path.trim()
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.source_path,
    pattern:
      typeof config.pattern === "string"
        ? config.pattern
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.pattern,
    destination_template:
      typeof config.destination_template === "string"
        ? config.destination_template
        : DEFAULT_ATTRIBUTE_UPDATE_FIELDS.destination_template,
    regex_flags: parseRegexFlags(config.regex_flags),
  };
}

export function parseUpdateAttributeConfig(
  config: Record<string, unknown>,
): UpdateAttributeConfig {
  if (Array.isArray(config.attributes)) {
    const attributes = config.attributes
      .map(parseAttributeUpdate)
      .filter((item): item is AttributeUpdate => item !== null);
    return { attributes };
  }

  const legacy = parseLegacyAttribute(config);
  if (legacy) {
    return { attributes: [legacy] };
  }

  return { attributes: EMPTY_ATTRIBUTES };
}

export function buildUpdateAttributeConfig(
  config: Record<string, unknown>,
  patch: Partial<UpdateAttributeConfig> = {},
): Record<string, unknown> {
  const current = parseUpdateAttributeConfig(config);
  const next: UpdateAttributeConfig = {
    attributes: patch.attributes ?? current.attributes,
  };
  return next as unknown as Record<string, unknown>;
}

export function summarizeAttributeUpdate(attribute: AttributeUpdate): string {
  if (attribute.mode === "fixed") {
    const value = attribute.fixed_value.trim() || "(empty)";
    return `${attribute.destination_path} = ${value}`;
  }
  return `${attribute.source_path} → ${attribute.destination_path}`;
}

export function deriveUpdateAttributeOutcomes(): WorkflowOutcomeField[] {
  return [{ name: "success" }];
}
