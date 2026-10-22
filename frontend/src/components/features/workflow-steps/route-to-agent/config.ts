import { boolField, numberField, stringField } from "../shared/config-field-helpers";

export interface RouteToAgentConfig {
  agent_source_id: string;
  handler: string;
  /** Static JSON object handed to the handler next to the per-device inputs. */
  params: Record<string, unknown>;
  input_paths: string[];
  content_inputs: string[];
  destination_path: string;
  output_keys: string[];
  allow_missing_outputs: boolean;
  timeout_seconds: number;
}

export const DEFAULT_TIMEOUT_SECONDS = 30;
export const TIMEOUT_RANGE = { min: 1, max: 600 } as const;
export const MAX_PARAMS_BYTES = 16 * 1024;

/** Device content the step can send as text. `command_output:<node_id>` is added per run-command step. */
export const STATIC_CONTENT_INPUTS = [
  { value: "running_config", label: "Running config" },
  { value: "startup_config", label: "Startup config" },
  { value: "latest_command_output", label: "Latest command output" },
] as const;
export const COMMAND_OUTPUT_PREFIX = "command_output:";

// These mirror backend/workflow_steps/route_to_agent/request.py so a mistake shows up in the
// editor instead of as a failed run; the backend remains the authority.
const HANDLER_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
const DEVICE_FIELD_NAMES = new Set([
  "id",
  "name",
  "hostname",
  "platform",
  "network_driver",
  "primary_ip4",
  "source",
  "source_id",
]);
const RESERVED_DESTINATION_ROOTS = new Set(["device", "error", "parsed", "run_input"]);

function stringListField(config: Record<string, unknown>, key: string): string[] {
  const value = config[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function paramsField(config: Record<string, unknown>): Record<string, unknown> {
  const value = config.params;
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function parseRouteToAgentConfig(config: Record<string, unknown>): RouteToAgentConfig {
  return {
    agent_source_id: stringField(config, "agent_source_id"),
    handler: stringField(config, "handler"),
    params: paramsField(config),
    input_paths: stringListField(config, "input_paths"),
    content_inputs: stringListField(config, "content_inputs"),
    destination_path: stringField(config, "destination_path"),
    output_keys: stringListField(config, "output_keys"),
    allow_missing_outputs: boolField(config, "allow_missing_outputs"),
    timeout_seconds: numberField(config, "timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
  };
}

export function buildRouteToAgentConfig(
  config: Record<string, unknown>,
  patch: Partial<RouteToAgentConfig>,
): Record<string, unknown> {
  return { ...config, ...parseRouteToAgentConfig(config), ...patch };
}

/** One entry per line (or comma separated); blanks and duplicates are dropped. */
export function parseLines(text: string): string[] {
  const seen = new Set<string>();
  const items: string[] = [];
  for (const raw of text.split(/[\n,]/)) {
    const item = raw.trim();
    if (item && !seen.has(item)) {
      seen.add(item);
      items.push(item);
    }
  }
  return items;
}

export function formatLines(items: string[]): string {
  return items.join("\n");
}

export type ParamsParseResult =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; error: string };

export function parseParamsText(text: string): ParamsParseResult {
  if (!text.trim()) {
    return { ok: true, value: {} };
  }
  if (new TextEncoder().encode(text).length > MAX_PARAMS_BYTES) {
    return { ok: false, error: "Params must be at most 16 KiB." };
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, error: "Params must be valid JSON." };
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, error: "Params must be a JSON object." };
  }
  return { ok: true, value: value as Record<string, unknown> };
}

function destinationProblem(path: string): string | null {
  if (!path.trim()) {
    return "Destination path is required.";
  }
  const segments = path.split(".");
  if (segments.length < 2) {
    return "Destination path must be bag.field, for example agent.geo.";
  }
  if (segments.some((segment) => !NAME_PATTERN.test(segment))) {
    return "Destination path segments may only contain letters, digits, '_' and '-'.";
  }
  const root = segments[0];
  if (RESERVED_DESTINATION_ROOTS.has(root) || DEVICE_FIELD_NAMES.has(root)) {
    return `Destination path may not start with "${root}"; write to a bag such as agent.<id>.`;
  }
  return null;
}

/** Human-readable problems that would make the backend reject this configuration. */
export function configProblems(config: RouteToAgentConfig): string[] {
  const problems: string[] = [];
  if (!config.agent_source_id.trim()) {
    problems.push("Choose an agent.");
  }
  if (!config.handler.trim()) {
    problems.push("Handler is required.");
  } else if (!HANDLER_PATTERN.test(config.handler.trim())) {
    problems.push("Handler may only contain letters, digits, '_', '.' and '-'.");
  }
  if (config.input_paths.length === 0 && config.content_inputs.length === 0) {
    problems.push("Select at least one input to send.");
  }
  const destination = destinationProblem(config.destination_path.trim());
  if (destination) {
    problems.push(destination);
  }
  if (config.output_keys.length === 0) {
    problems.push("List the output keys the agent returns.");
  } else if (config.output_keys.some((key) => !NAME_PATTERN.test(key))) {
    problems.push("Output keys must be plain names (letters, digits, '_', '-'; no dots).");
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
