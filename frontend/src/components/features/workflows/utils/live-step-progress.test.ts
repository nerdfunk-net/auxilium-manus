import { describe, expect, it } from "vitest";

import type { WorkflowRunDeviceGroup, WorkflowStepResult } from "../types/workflow-runs";
import { deriveLiveStepProgress, summarizeDeviceGroups } from "./live-step-progress";

function step(overrides: Partial<WorkflowStepResult> = {}): WorkflowStepResult {
  return {
    id: 1,
    run_id: 1,
    step_node_id: "a",
    step_type: "run-command",
    step_name: "Run command",
    status: "pending",
    started_at: null,
    finished_at: null,
    output: null,
    error_message: null,
    error_category: null,
    error_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function group(
  childIndex: number,
  nodeStates: Record<string, string>,
  status: WorkflowRunDeviceGroup["status"] = "running",
): WorkflowRunDeviceGroup {
  return {
    child_index: childIndex,
    device_names: [`r${childIndex}`],
    status,
    node_states: nodeStates,
    error_message: null,
    started_at: null,
    finished_at: null,
  };
}

describe("deriveLiveStepProgress", () => {
  it("falls back to the persisted status when there are no device groups", () => {
    expect(deriveLiveStepProgress(step(), [])).toEqual({ status: "pending", detail: null });
  });

  it("keeps a pending step pending while no group has reached it", () => {
    const groups = [group(0, {}, "pending"), group(1, {}, "pending")];
    expect(deriveLiveStepProgress(step(), groups)).toEqual({ status: "pending", detail: null });
  });

  it("shows running with a group count once any group reaches the step", () => {
    const groups = [group(0, { a: "running" }), group(1, {}, "pending"), group(2, { a: "success" })];
    expect(deriveLiveStepProgress(step(), groups)).toEqual({
      status: "running",
      detail: "1/3 groups done · 1 running",
    });
  });

  it("derives a terminal status once every group finished the step", () => {
    const allOk = [group(0, { a: "success" }), group(1, { a: "success" })];
    expect(deriveLiveStepProgress(step(), allOk).status).toBe("success");

    const mixed = [group(0, { a: "success" }), group(1, { a: "failed" })];
    expect(deriveLiveStepProgress(step(), mixed)).toEqual({
      status: "partial",
      detail: "2/2 groups done",
    });

    const allFailed = [group(0, { a: "failed" }), group(1, { a: "failed" })];
    expect(deriveLiveStepProgress(step(), allFailed).status).toBe("failed");
  });

  it("treats skipped groups as done without turning the step into a failure", () => {
    const groups = [group(0, { a: "success" }), group(1, { a: "skipped" })];
    expect(deriveLiveStepProgress(step(), groups).status).toBe("success");
  });

  it("never overrides a step the parent already persisted as finished", () => {
    const groups = [group(0, { a: "running" })];
    expect(deriveLiveStepProgress(step({ status: "success" }), groups)).toEqual({
      status: "success",
      detail: null,
    });
    expect(deriveLiveStepProgress(step({ status: "failed" }), groups).status).toBe("failed");
  });

  it("ignores node states for other steps", () => {
    const groups = [group(0, { other: "running" })];
    expect(deriveLiveStepProgress(step(), groups)).toEqual({ status: "pending", detail: null });
  });
});

describe("summarizeDeviceGroups", () => {
  it("counts groups by status", () => {
    const groups = [
      group(0, {}, "pending"),
      group(1, {}, "running"),
      group(2, {}, "success"),
      group(3, {}, "partial"),
      group(4, {}, "failed"),
    ];
    expect(summarizeDeviceGroups(groups)).toEqual({
      total: 5,
      pending: 1,
      running: 1,
      success: 1,
      partial: 1,
      failed: 1,
      finished: 3,
    });
  });
});
