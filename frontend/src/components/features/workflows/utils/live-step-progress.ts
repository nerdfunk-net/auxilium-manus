import type { WorkflowRunDeviceGroup, WorkflowStepResult } from "../types/workflow-runs";
import { deriveStepDisplayStatus, type DerivedStepStatus } from "./step-result-status";

export interface LiveStepProgress {
  status: DerivedStepStatus;
  /** e.g. "3/12 groups done · 2 running"; null when the persisted status is authoritative. */
  detail: string | null;
}

const DONE_STATES = new Set(["success", "partial", "failed", "skipped"]);

/**
 * Fan-out children write no step rows — the parent only persists them once the
 * children finish — so a child-branch step stays "pending" in the DB while
 * device groups are already running it. Overlay the groups' live per-node state
 * on such rows. A step the parent already persisted is never overridden.
 */
export function deriveLiveStepProgress(
  step: WorkflowStepResult,
  deviceGroups: readonly WorkflowRunDeviceGroup[],
): LiveStepProgress {
  const persisted: LiveStepProgress = {
    status: deriveStepDisplayStatus(step.status, step.output),
    detail: null,
  };
  if (step.status !== "pending" && step.status !== "running") {
    return persisted;
  }

  const states = deviceGroups
    .map((group) => group.node_states[step.step_node_id])
    .filter((state): state is string => state !== undefined);
  if (states.length === 0) {
    return persisted;
  }

  const done = states.filter((state) => DONE_STATES.has(state)).length;
  const running = states.filter((state) => state === "running").length;
  const total = deviceGroups.length;

  if (done < total) {
    return {
      status: "running",
      detail: `${done}/${total} groups done${running > 0 ? ` · ${running} running` : ""}`,
    };
  }

  const executed = states.filter((state) => state !== "skipped");
  const failed = executed.filter((state) => state === "failed").length;
  const partial = executed.filter((state) => state === "partial").length;
  let status: DerivedStepStatus = "success";
  if (executed.length === 0) {
    status = "skipped";
  } else if (failed === executed.length) {
    status = "failed";
  } else if (failed > 0 || partial > 0) {
    status = "partial";
  }
  return { status, detail: `${done}/${total} groups done` };
}

export interface DeviceGroupSummary {
  total: number;
  pending: number;
  running: number;
  success: number;
  partial: number;
  failed: number;
  /** success + partial + failed */
  finished: number;
}

export function summarizeDeviceGroups(
  deviceGroups: readonly WorkflowRunDeviceGroup[],
): DeviceGroupSummary {
  const summary: DeviceGroupSummary = {
    total: deviceGroups.length,
    pending: 0,
    running: 0,
    success: 0,
    partial: 0,
    failed: 0,
    finished: 0,
  };
  for (const group of deviceGroups) {
    summary[group.status] += 1;
  }
  summary.finished = summary.success + summary.partial + summary.failed;
  return summary;
}
