import { parseRetryBackoffSeconds } from "@/components/features/workflow-steps/shared/retry-backoff-fields";

import { pyatsSourceIdFromConfig, PYATS_SOURCE_ID_KEY } from "../shared/pyats-source-config";

const DEFAULT_COMMANDS = ["show version"];
const DEFAULT_PARSED_OUTPUT_KEY = "parsed";
export const DEFAULT_READ_TIMEOUT = 60;
export const MIN_READ_TIMEOUT = 5;
export const MAX_READ_TIMEOUT = 600;

export type ParserMode = "none" | "textfsm" | "genie";

export const PARSER_MODE_OPTIONS: { value: ParserMode; label: string }[] = [
  { value: "none", label: "None (raw text only)" },
  { value: "textfsm", label: "TextFSM (netmiko/ntc-templates)" },
  { value: "genie", label: "Genie (pyATS)" },
];

export const EXECUTION_MODE_OPTIONS = [
  {
    value: "exec_mode",
    label: "Exec mode",
    hint: "Sends each command individually as an exec-level command (current behavior).",
  },
  {
    value: "config_mode",
    label: "Configuration mode",
    hint: "Enters configuration mode once, sends every command, then exits — like Deploy Rendered Template.",
  },
] as const;

export type ExecutionMode = (typeof EXECUTION_MODE_OPTIONS)[number]["value"];

export function parseCommands(config: Record<string, unknown>): string[] {
  const raw = config.commands;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [...DEFAULT_COMMANDS];
  }
  return raw.map((item) => (typeof item === "string" ? item : ""));
}

export function parseParserMode(config: Record<string, unknown>): ParserMode {
  return config.parser === "textfsm" || config.parser === "genie" ? config.parser : "none";
}

export function parseParsedOutputKey(config: Record<string, unknown>): string {
  return typeof config.parsed_output_key === "string" && config.parsed_output_key.trim()
    ? config.parsed_output_key
    : DEFAULT_PARSED_OUTPUT_KEY;
}

export function buildRunCommandConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    credential_reference:
      typeof config.credential_reference === "string" ? config.credential_reference : "",
    credential_source: config.credential_source === "run_param" ? "run_param" : "fixed",
    credential_param:
      typeof config.credential_param === "string" ? config.credential_param : "",
    commands: parseCommands(config),
    parser: parseParserMode(config),
    network_driver_override:
      typeof config.network_driver_override === "string"
        ? config.network_driver_override
        : "",
    [PYATS_SOURCE_ID_KEY]: pyatsSourceIdFromConfig(config),
    parsed_output_key: parseParsedOutputKey(config),
    execution_mode: config.execution_mode === "config_mode" ? "config_mode" : "exec_mode",
    write_config_after_execution: config.write_config_after_execution === true,
    read_timeout:
      typeof config.read_timeout === "number" && Number.isFinite(config.read_timeout)
        ? config.read_timeout
        : DEFAULT_READ_TIMEOUT,
    auto_confirm_prompts: config.auto_confirm_prompts === true,
    dry_run: config.dry_run === true,
    retry_backoff_seconds: parseRetryBackoffSeconds(config),
    ...patch,
  };

  const executionMode: ExecutionMode = merged.execution_mode === "config_mode" ? "config_mode" : "exec_mode";
  const autoConfirmPrompts = merged.auto_confirm_prompts === true;
  const parserLocked = executionMode === "config_mode" || autoConfirmPrompts;

  return {
    ...merged,
    execution_mode: executionMode,
    auto_confirm_prompts: autoConfirmPrompts,
    // parser is mutually exclusive with config_mode/auto_confirm_prompts — force it
    // back to "none" regardless of what the incoming patch tried to set it to.
    parser: parserLocked ? "none" : (merged.parser as ParserMode),
    // write_config_after_execution only applies in config_mode.
    write_config_after_execution:
      executionMode === "config_mode" ? merged.write_config_after_execution : false,
  };
}

export function clampReadTimeout(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_READ_TIMEOUT, Math.max(MIN_READ_TIMEOUT, parsed))
    : DEFAULT_READ_TIMEOUT;
}
