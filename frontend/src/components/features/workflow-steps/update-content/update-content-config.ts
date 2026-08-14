export interface RegexFlags {
  case_insensitive: boolean;
  multiline: boolean;
  dotall: boolean;
}

export type ContentSource = "running_config" | "startup_config";

export interface ContentReplaceRule {
  id: string;
  pattern: string;
  replacement: string;
  regex_flags: RegexFlags;
  replace_all: boolean;
}

export interface UpdateContentConfig {
  content_source: ContentSource;
  replace_rules: ContentReplaceRule[];
}

export const CONTENT_SOURCE_OPTIONS: { value: ContentSource; label: string }[] = [
  { value: "running_config", label: "Running config" },
  { value: "startup_config", label: "Startup config" },
];

export const DEFAULT_REGEX_FLAGS: RegexFlags = {
  case_insensitive: false,
  multiline: false,
  dotall: false,
};

export const DEFAULT_REPLACE_RULE_FIELDS: Omit<ContentReplaceRule, "id"> = {
  pattern: String.raw`ntp server 192\.168\.1\.10`,
  replacement: "ntp server 192.168.178.10",
  regex_flags: DEFAULT_REGEX_FLAGS,
  replace_all: true,
};

export const DEFAULT_UPDATE_CONTENT_CONFIG: UpdateContentConfig = {
  content_source: "running_config",
  replace_rules: [],
};

const EMPTY_RULES: ContentReplaceRule[] = [];

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

function parseContentSource(raw: unknown): ContentSource {
  return raw === "startup_config" ? "startup_config" : "running_config";
}

function newRuleId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `rule-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function createReplaceRule(
  patch: Partial<Omit<ContentReplaceRule, "id">> = {},
): ContentReplaceRule {
  return {
    id: newRuleId(),
    ...DEFAULT_REPLACE_RULE_FIELDS,
    ...patch,
    regex_flags: {
      ...DEFAULT_REGEX_FLAGS,
      ...(patch.regex_flags ?? {}),
    },
  };
}

function parseReplaceRule(raw: unknown): ContentReplaceRule | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const item = raw as Record<string, unknown>;
  return {
    id: typeof item.id === "string" && item.id.trim() ? item.id.trim() : newRuleId(),
    pattern: typeof item.pattern === "string" ? item.pattern : "",
    replacement: typeof item.replacement === "string" ? item.replacement : "",
    regex_flags: parseRegexFlags(item.regex_flags),
    replace_all: item.replace_all !== false,
  };
}

export function parseUpdateContentConfig(
  config: Record<string, unknown>,
): UpdateContentConfig {
  const replace_rules = Array.isArray(config.replace_rules)
    ? config.replace_rules
        .map(parseReplaceRule)
        .filter((item): item is ContentReplaceRule => item !== null)
    : EMPTY_RULES;
  return {
    content_source: parseContentSource(config.content_source),
    replace_rules,
  };
}

export function buildUpdateContentConfig(
  config: Record<string, unknown>,
  patch: Partial<UpdateContentConfig> = {},
): Record<string, unknown> {
  const current = parseUpdateContentConfig(config);
  const next: UpdateContentConfig = {
    content_source: patch.content_source ?? current.content_source,
    replace_rules: patch.replace_rules ?? current.replace_rules,
  };
  return next as unknown as Record<string, unknown>;
}

export function summarizeReplaceRule(rule: ContentReplaceRule): string {
  const pattern = rule.pattern.trim() || "(empty pattern)";
  const replacement = rule.replacement.trim() || "(empty)";
  return `${pattern} → ${replacement}`;
}
