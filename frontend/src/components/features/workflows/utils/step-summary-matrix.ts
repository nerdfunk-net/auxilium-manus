import { parseStepOutput } from "@/lib/workflow-context-types";
import type { DeviceError } from "@/lib/workflow-context-types";

import type { WorkflowStepResult } from "../types/workflow-runs";

export type SummaryCellStatus = "success" | "device-error" | "step-error" | "neutral";

export interface SummaryCell {
  status: SummaryCellStatus;
  errors: DeviceError[];
}

export interface SummaryDeviceRow {
  id: string;
  name: string;
  hostname: string;
}

export interface StepSummaryMatrix {
  devices: SummaryDeviceRow[];
  columns: WorkflowStepResult[];
  getCell: (stepId: number, deviceId: string) => SummaryCell;
}

const NEUTRAL_CELL: SummaryCell = { status: "neutral", errors: [] };

function collectDeviceRows(steps: WorkflowStepResult[]): SummaryDeviceRow[] {
  const rows = new Map<string, SummaryDeviceRow>();
  for (const step of steps) {
    const envelope = parseStepOutput(step.output);
    if (!envelope) continue;
    for (const context of Object.values(envelope.outcomes)) {
      for (const device of Object.values(context.devices)) {
        if (!rows.has(device.id)) {
          rows.set(device.id, { id: device.id, name: device.name, hostname: device.hostname });
        }
      }
    }
  }
  return Array.from(rows.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function cellForStep(step: WorkflowStepResult, deviceId: string): SummaryCell {
  if (step.status === "skipped") {
    return NEUTRAL_CELL;
  }
  if (step.error_message) {
    return { status: "step-error", errors: [] };
  }

  const envelope = parseStepOutput(step.output);
  if (!envelope) {
    return NEUTRAL_CELL;
  }

  for (const context of Object.values(envelope.outcomes)) {
    const device = context.devices[deviceId];
    if (!device) continue;
    if (device.status === "ok" && device.errors.length === 0) {
      return { status: "success", errors: [] };
    }
    if (device.status === "failed" || device.errors.length > 0) {
      return { status: "device-error", errors: device.errors };
    }
    return NEUTRAL_CELL;
  }

  return NEUTRAL_CELL;
}

/** Builds the device x step status matrix for the "Show Summary" step from
 * the run's full step_results list. Excludes show-summary steps themselves
 * and steps that have not executed yet. */
export function buildStepSummaryMatrix(steps: WorkflowStepResult[]): StepSummaryMatrix {
  const columns = steps.filter(
    (step) => step.step_type !== "show-summary" && step.status !== "pending",
  );
  const devices = collectDeviceRows(columns);
  const stepsById = new Map(columns.map((step) => [step.id, step]));

  const cellCache = new Map<string, SummaryCell>();
  const getCell = (stepId: number, deviceId: string): SummaryCell => {
    const cacheKey = `${stepId}:${deviceId}`;
    const cached = cellCache.get(cacheKey);
    if (cached) return cached;
    const step = stepsById.get(stepId);
    const cell = step ? cellForStep(step, deviceId) : NEUTRAL_CELL;
    cellCache.set(cacheKey, cell);
    return cell;
  };

  return { devices, columns, getCell };
}
