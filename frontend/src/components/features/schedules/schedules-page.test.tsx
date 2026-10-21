import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SchedulesPage } from "./schedules-page";

const h = vi.hoisted(() => ({
  runNow: { mutate: vi.fn(), isPending: false },
  state: { data: undefined, isLoading: false, error: null } as {
    data: unknown[] | undefined;
    isLoading: boolean;
    error: Error | null;
  },
}));
vi.mock("./hooks/use-schedules-query", () => ({ useSchedulesQuery: () => h.state }));
vi.mock("./hooks/use-schedule-mutations", () => ({
  useScheduleMutations: () => ({
    deleteSchedule: { mutateAsync: vi.fn(), isPending: false },
    toggleSchedule: { mutateAsync: vi.fn(), isPending: false },
    runNow: h.runNow,
  }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("./dialogs/schedule-editor-dialog", () => ({ ScheduleEditorDialog: () => null }));

afterEach(() => {
  cleanup();
  h.state = { data: undefined, isLoading: false, error: null };
});

describe("SchedulesPage", () => {
  it("shows the empty state when the list loaded and is empty", () => {
    h.state = { data: [], isLoading: false, error: null };
    render(<SchedulesPage />);
    expect(screen.getByText("No schedules yet.")).toBeTruthy();
  });

  it("shows the error, not the empty state, when the list could not be loaded", () => {
    h.state = { data: undefined, isLoading: false, error: new Error("Permission denied: schedules:read required") };
    render(<SchedulesPage />);
    expect(screen.getByText("Permission denied: schedules:read required")).toBeTruthy();
    expect(screen.queryByText("No schedules yet.")).toBeNull();
  });

  it("starts a run for the schedule only after the user confirms", () => {
    h.state = {
      data: [
        {
          id: 5,
          workflow_id: 9,
          workflow_name: "Backup",
          name: "Nightly",
          schedule_type: "cron",
          cron_expression: "0 2 * * *",
          run_at: null,
          enabled: true,
          run_inputs: {},
          concurrency_limit: 1,
          last_triggered_at: null,
        },
      ],
      isLoading: false,
      error: null,
    };
    render(<SchedulesPage />);
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(h.runNow.mutate).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Run now" }));
    expect(h.runNow.mutate).toHaveBeenCalledWith(
      { id: 5, workflowId: 9 },
      expect.objectContaining({ onSettled: expect.any(Function) }),
    );
  });
});
