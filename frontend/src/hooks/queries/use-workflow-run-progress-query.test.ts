import { describe, expect, it } from "vitest";

import type { WorkflowRunProgress } from "@/components/features/workflows/types/workflow-runs";

import {
  ACTIVE_POLL_INTERVAL_MS,
  PAUSED_POLL_INTERVAL_MS,
  progressRefetchInterval,
  progressSignature,
} from "./use-workflow-run-progress-query";

function progress(overrides: Partial<WorkflowRunProgress> = {}): WorkflowRunProgress {
  return {
    id: 1,
    status: "running",
    current_node_id: "n1",
    approval_state: null,
    error_message: null,
    started_at: "2026-10-15T10:00:00Z",
    finished_at: null,
    steps: [{ step_node_id: "n1", status: "running", started_at: null, finished_at: null, has_error: false }],
    device_groups: [],
    ...overrides,
  };
}

describe("progressRefetchInterval", () => {
  it("polls until terminal then stops", () => {
    expect(progressRefetchInterval(undefined)).toBe(ACTIVE_POLL_INTERVAL_MS);
    expect(progressRefetchInterval(progress({ status: "pending" }))).toBe(ACTIVE_POLL_INTERVAL_MS);
    expect(progressRefetchInterval(progress({ status: "running" }))).toBe(ACTIVE_POLL_INTERVAL_MS);
    expect(progressRefetchInterval(progress({ status: "paused" }))).toBe(PAUSED_POLL_INTERVAL_MS);
    for (const status of ["success", "failed", "cancelled"]) {
      expect(progressRefetchInterval(progress({ status }))).toBe(false);
    }
  });
});

describe("progressSignature", () => {
  it("is stable while nothing changes", () => {
    expect(progressSignature(progress())).toBe(progressSignature(progress()));
  });

  it("changes when a step finishes or the run ends, so the full run is fetched once", () => {
    const base = progressSignature(progress());
    const stepDone = progress({
      steps: [
        { step_node_id: "n1", status: "success", started_at: null, finished_at: "x", has_error: false },
      ],
    });
    expect(progressSignature(stepDone)).not.toBe(base);
    expect(progressSignature(progress({ status: "success", finished_at: "x" }))).not.toBe(base);
  });
});
