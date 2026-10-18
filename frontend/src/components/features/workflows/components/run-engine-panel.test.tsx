import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HatchetRunDiagnostics } from "@/hooks/queries/use-hatchet-diagnostics-query";
import { RunEnginePanel } from "./run-engine-panel";

const queryState = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
}));

vi.mock("@/hooks/queries/use-hatchet-diagnostics-query", () => ({
  useHatchetRunDiagnosticsQuery: () => queryState.current,
}));

const BASE: HatchetRunDiagnostics = {
  engine_reachable: true,
  message: "OK",
  hatchet_run_id: "hr-1",
  engine_status: "RUNNING",
  mismatch: null,
  dashboard_url: null,
  tasks: [],
  events: [],
  child_runs: [],
  child_summary: null,
  events_truncated: false,
};

function show(data: Partial<HatchetRunDiagnostics> | undefined, extra: Record<string, unknown> = {}) {
  queryState.current = {
    data: data ? { ...BASE, ...data } : undefined,
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    ...extra,
  };
  render(<RunEnginePanel runId={42} />);
}

afterEach(cleanup);

describe("RunEnginePanel", () => {
  it("shows a loading state", () => {
    show(undefined, { isLoading: true });
    expect(screen.getByText(/asking the engine/i)).toBeTruthy();
  });

  it("shows a load failure without details", () => {
    show(undefined, { isError: true });
    expect(screen.getByText(/could not be loaded/i)).toBeTruthy();
  });

  it("reports an unreachable engine with the server message", () => {
    show({ engine_reachable: false, engine_status: null, message: "engine down" });
    expect(screen.getByText("unreachable")).toBeTruthy();
    expect(screen.getByText("engine down")).toBeTruthy();
  });

  it("flags a mismatch between the app and the engine", () => {
    show({ mismatch: "The engine reports FAILED but the run is still running here" });
    expect(screen.getByText(/app and engine disagree/i)).toBeTruthy();
    expect(screen.getByText(/engine reports FAILED/)).toBeTruthy();
  });

  it("lists tasks and child runs", () => {
    show({
      child_summary: {
        total: 1,
        completed: 0,
        failed: 0,
        cancelled: 0,
        running: 0,
        queued: 1,
        exact: true,
        listed: 1,
        truncated: false,
      },
      tasks: [
        {
          name: "execute_steps",
          status: "FAILED",
          attempt: 2,
          retry_count: 1,
          started_at: null,
          finished_at: null,
          duration_ms: 1500,
          error_message: "boom",
        },
      ],
      child_runs: [
        {
          hatchet_run_id: "c-1",
          name: "DeviceGroupExecution",
          status: "COMPLETED",
          child_index: "3",
          started_at: null,
          finished_at: null,
          error_message: null,
        },
      ],
    });
    expect(screen.getByText("execute_steps")).toBeTruthy();
    expect(screen.getByText("1.5 s")).toBeTruthy();
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.getByText("#3")).toBeTruthy();
  });

  const SUMMARY = {
    total: 412,
    completed: 380,
    failed: 4,
    cancelled: 0,
    running: 16,
    queued: 12,
    exact: true,
    listed: 32,
    truncated: false,
  };

  it("summarises the groups by status", () => {
    show({ child_summary: SUMMARY });
    expect(screen.getByText("412 groups")).toBeTruthy();
    expect(screen.getByText("380 completed")).toBeTruthy();
    expect(screen.getByText("4 failed")).toBeTruthy();
    expect(screen.queryByText(/approximate/)).toBeNull();
    expect(screen.queryByText(/Showing/)).toBeNull();
  });

  it("says how many failed and active groups are not shown", () => {
    show({
      child_summary: {
        ...SUMMARY,
        failed: 120,
        running: 20,
        queued: 12,
        listed: 150,
        truncated: true,
      },
      dashboard_url: "http://hatchet/run/1",
    });
    expect(screen.getByText(/Showing 150 of 152 failed and active groups/)).toBeTruthy();
    expect(screen.getByText("See all in Hatchet")).toBeTruthy();
  });

  it("does not claim a total when the counts are approximate", () => {
    show({
      child_summary: { ...SUMMARY, exact: false, listed: 100, truncated: true },
    });
    expect(screen.getByText(/Showing 100 failed and active groups; there may be more/)).toBeTruthy();
    expect(screen.queryByText(/of 100/)).toBeNull();
  });

  it("says when every group completed", () => {
    show({
      child_summary: { ...SUMMARY, total: 50, completed: 50, failed: 0, running: 0, queued: 0, listed: 0 },
    });
    expect(screen.getByText(/no failed or active groups/i)).toBeTruthy();
  });

  it("flags totals that are only approximate", () => {
    show({ child_summary: { ...SUMMARY, exact: false } });
    expect(screen.getByText(/approximate/)).toBeTruthy();
  });

  it("notes that older engine events are not shown", () => {
    show({
      events_truncated: true,
      events: [
        {
          task_name: "t",
          event_type: "STARTED",
          timestamp: "2026-10-18T12:00:00Z",
          message: "m",
          error_message: null,
          attempt: 1,
        },
      ],
    });
    expect(screen.getByText(/older events not shown/)).toBeTruthy();
  });
});
