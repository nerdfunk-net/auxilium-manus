import { fanOutFromConfig, type FanOutConfig } from "../shared/fan-out-config";
import { numberField, stringField } from "../shared/config-field-helpers";

export interface AgentAttribute {
  name: string;
  value: string;
}

export interface GetFromAgentConfig {
  agent_source_id: string;
  handler: string;
  attributes: AgentAttribute[];
  timeout_seconds: number;
  fan_out: FanOutConfig;
}

export const DEFAULT_TIMEOUT_SECONDS = 30;
export const TIMEOUT_RANGE = { min: 1, max: 600 } as const;
export const MAX_ATTRIBUTES = 64;

// These mirror backend/workflow_steps/get_from_agent/request.py so a mistake shows up in the
// editor instead of as a failed run; the backend remains the authority.
const HANDLER_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
export const MAX_VALUE_CHARS = 4096;

// Mirrors is_secret_key_name in backend/services/workflow_context/secret_fields.py.
const SECRET_NAMES = new Set([
  "password",
  "secret",
  "token",
  "community",
  "shared_secret",
  "sharedsecret",
  "passphrase",
  "api_key",
  "apikey",
  "enable_secret",
  "snmp_community",
  "secret_key",
  "private_key",
  "auth_key",
  "shared_key",
  "tacacs_key",
  "db_pw",
]);
const SECRET_SUFFIXES = [
  "_password",
  "_secret",
  "_token",
  "_passphrase",
  "_key",
  "_pw",
  "_pass",
  "_passwd",
  "_psk",
  "_community",
];
const RUN_INPUT_REFERENCE = /^\{run_input\.[A-Za-z_][A-Za-z0-9_-]{0,63}\}$/;

export function isSecretName(name: string): boolean {
  const lowered = name.replace(/-/g, "_").toLowerCase();
  return SECRET_NAMES.has(lowered) || SECRET_SUFFIXES.some((suffix) => lowered.endsWith(suffix));
}

const EMPTY_ATTRIBUTE: AgentAttribute = { name: "", value: "" };

export function emptyAttribute(): AgentAttribute {
  return { ...EMPTY_ATTRIBUTE };
}

function attributesField(config: Record<string, unknown>): AgentAttribute[] {
  const raw = config.attributes;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .filter((item): item is Record<string, unknown> => item !== null && typeof item === "object")
    .map((item) => ({
      name: typeof item.name === "string" ? item.name : "",
      value: item.value === undefined || item.value === null ? "" : String(item.value),
    }));
}

export function parseGetFromAgentConfig(config: Record<string, unknown>): GetFromAgentConfig {
  return {
    agent_source_id: stringField(config, "agent_source_id"),
    handler: stringField(config, "handler"),
    attributes: attributesField(config),
    timeout_seconds: numberField(config, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
    fan_out: fanOutFromConfig(config),
  };
}

export function buildGetFromAgentConfig(
  config: Record<string, unknown>,
  patch: Partial<GetFromAgentConfig>,
): Record<string, unknown> {
  return { ...config, ...parseGetFromAgentConfig(config), ...patch };
}

/** Human-readable problems that would make the backend reject this configuration. */
export function configProblems(config: GetFromAgentConfig): string[] {
  const problems: string[] = [];
  if (!config.agent_source_id.trim()) {
    problems.push("Choose an agent.");
  }
  if (!config.handler.trim()) {
    problems.push("Handler is required.");
  } else if (!HANDLER_PATTERN.test(config.handler.trim())) {
    problems.push("Handler may only contain letters, digits, '_', '.' and '-'.");
  }
  const named = config.attributes.filter((row) => row.name.trim() || row.value.trim());
  if (named.some((row) => !NAME_PATTERN.test(row.name.trim()))) {
    problems.push("Attribute names must be plain names (letters, digits, '_', '-').");
  }
  if (named.some((row) => isSecretName(row.name.trim()))) {
    problems.push("Attribute names that look like secrets are never sent to an agent.");
  }
  if (named.some((row) => row.value.length > MAX_VALUE_CHARS)) {
    problems.push(`Attribute values may be at most ${MAX_VALUE_CHARS} characters.`);
  }
  if (
    named.some(
      (row) => row.value.includes("{run_input.") && !RUN_INPUT_REFERENCE.test(row.value.trim()),
    )
  ) {
    problems.push("A run input reference must be the whole value, like {run_input.site}.");
  }
  const names = named.map((row) => row.name.trim());
  if (new Set(names).size !== names.length) {
    problems.push("Attribute names must be unique.");
  }
  if (named.length > MAX_ATTRIBUTES) {
    problems.push(`At most ${MAX_ATTRIBUTES} attributes can be sent.`);
  }
  if (
    !Number.isInteger(config.timeout_seconds) ||
    config.timeout_seconds < TIMEOUT_RANGE.min ||
    config.timeout_seconds > TIMEOUT_RANGE.max
  ) {
    problems.push(`Timeout must be between ${TIMEOUT_RANGE.min} and ${TIMEOUT_RANGE.max} seconds.`);
  }
  return problems;
}
