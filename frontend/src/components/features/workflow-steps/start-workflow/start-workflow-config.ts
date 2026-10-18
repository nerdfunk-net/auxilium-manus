import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

/** Limits mirrored from backend/workflow_steps/start_workflow/executor.py. */
export const MIN_WAIT_SECONDS = 5;
export const MAX_WAIT_SECONDS = 600;
export const DEFAULT_WAIT_SECONDS = 300;
export const MIN_POLL_SECONDS = 1;
export const MAX_POLL_SECONDS = 60;
export const DEFAULT_POLL_SECONDS = 5;
export const MIN_MAX_RUNS = 1;
export const MAX_MAX_RUNS = 200;
export const DEFAULT_MAX_RUNS = 25;

export type RunMode = "all_devices" | "per_device";

export interface StartWorkflowConfig {
  workflow_id: number | null;
  workflow_name: string;
  /** Name of the started workflow's text input that receives this workflow's devices. */
  devices_input: string;
  run_mode: RunMode;
  max_runs: number;
  run_inputs: Record<string, unknown>;
  wait: boolean;
  wait_seconds: number;
  poll_interval_seconds: number;
  allow_partial: boolean;
}

export function clampNumber(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function startWorkflowFromConfig(
  config: Record<string, unknown>,
): StartWorkflowConfig {
  const rawId = Number(config.workflow_id);
  const devicesInput =
    typeof config.devices_input === "string" ? config.devices_input.trim() : "";
  return {
    workflow_id: Number.isInteger(rawId) && rawId > 0 ? rawId : null,
    workflow_name:
      typeof config.workflow_name === "string" ? config.workflow_name : "",
    devices_input: devicesInput,
    // one run per device only makes sense with an input to put the device in
    run_mode:
      config.run_mode === "per_device" && devicesInput
        ? "per_device"
        : "all_devices",
    max_runs: clampNumber(
      config.max_runs,
      MIN_MAX_RUNS,
      MAX_MAX_RUNS,
      DEFAULT_MAX_RUNS,
    ),
    run_inputs: isRecord(config.run_inputs) ? config.run_inputs : {},
    wait: config.wait !== false && config.wait !== "false",
    wait_seconds: clampNumber(
      config.wait_seconds,
      MIN_WAIT_SECONDS,
      MAX_WAIT_SECONDS,
      DEFAULT_WAIT_SECONDS,
    ),
    poll_interval_seconds: clampNumber(
      config.poll_interval_seconds,
      MIN_POLL_SECONDS,
      MAX_POLL_SECONDS,
      DEFAULT_POLL_SECONDS,
    ),
    allow_partial:
      config.allow_partial === true || config.allow_partial === "true",
  };
}

interface CanvasNodeLike {
  data?: {
    kind?: string;
    disabled?: boolean;
    pluginConfig?: Record<string, unknown>;
  };
}

export interface TargetAnalysis {
  /** Text inputs an enabled Get from User step of the target reads its devices from. */
  deviceInputs: string[];
  /** Inputs the form fills by hand: everything except the device inputs and secrets. */
  otherAttributes: StaticAttributeDef[];
  /** Secret inputs can never be given by a step (the value would sit in the canvas). */
  secretNames: string[];
}

export function analyseTarget(
  canvasNodes: readonly unknown[] | null | undefined,
  staticAttributes: readonly StaticAttributeDef[] | null | undefined,
): TargetAnalysis {
  const attributes = staticAttributes ?? [];
  const readByGetFromUser = new Set<string>();
  for (const raw of canvasNodes ?? []) {
    const node = raw as CanvasNodeLike;
    if (node?.data?.kind !== "get-from-user" || node.data.disabled === true)
      continue;
    const param = node.data.pluginConfig?.device_param;
    if (typeof param === "string" && param.trim())
      readByGetFromUser.add(param.trim());
  }
  const deviceInputs = attributes
    .filter(
      (attr) => attr.type === "string" && readByGetFromUser.has(attr.name),
    )
    .map((attr) => attr.name);
  return {
    deviceInputs,
    otherAttributes: attributes.filter(
      (attr) => attr.type !== "secret" && !deviceInputs.includes(attr.name),
    ),
    secretNames: attributes
      .filter((attr) => attr.type === "secret")
      .map((attr) => attr.name),
  };
}

function isBlank(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (typeof value === "string" && value.trim() === "") ||
    (typeof value === "number" && Number.isNaN(value))
  );
}

/** Drop empty values so a cleared field falls back to the input's default. */
export function cleanRunInputs(
  values: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => !isBlank(value)),
  );
}

/** Names of required inputs without a default that the step still has to fill. */
export function missingRequiredInputs(
  attributes: readonly StaticAttributeDef[],
  values: Record<string, unknown>,
): string[] {
  return attributes
    .filter(
      (attr) =>
        attr.required && isBlank(attr.default) && isBlank(values[attr.name]),
    )
    .map((attr) => attr.name);
}

/** The calling workflow fans out, so this step may run once per fanned-out child. */
export function callerFansOut(nodes: readonly unknown[] | undefined): boolean {
  return (nodes ?? []).some((raw) => {
    const config = (raw as CanvasNodeLike)?.data?.pluginConfig;
    const fanOut = config?.fan_out;
    return isRecord(fanOut) && fanOut.enabled === true;
  });
}
