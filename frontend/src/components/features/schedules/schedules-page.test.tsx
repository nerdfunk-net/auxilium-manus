import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SchedulesPage } from "./schedules-page";

const h = vi.hoisted(() => ({
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
    runNow: { mutateAsync: vi.fn(), isPending: false },
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
});
