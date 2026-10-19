import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChangeRequestsPage } from "./change-requests-page";

const h = vi.hoisted(() => ({
  state: { data: undefined, isLoading: false, error: null } as {
    data: { items: unknown[] } | undefined;
    isLoading: boolean;
    error: Error | null;
  },
}));
vi.mock("./hooks/use-change-requests-query", () => ({ useChangeRequestsQuery: () => h.state }));
vi.mock("./components/change-request-detail-pane", () => ({ ChangeRequestDetailPane: () => null }));

afterEach(() => {
  cleanup();
  h.state = { data: undefined, isLoading: false, error: null };
});

describe("ChangeRequestsPage", () => {
  it("shows the empty state when the list loaded and is empty", () => {
    h.state = { data: { items: [] }, isLoading: false, error: null };
    render(<ChangeRequestsPage />);
    expect(screen.getByText(/No change requests yet/)).toBeTruthy();
  });

  it("shows the error, not the empty state, when the list could not be loaded", () => {
    h.state = { data: undefined, isLoading: false, error: new Error("Permission denied: change_requests:read required") };
    render(<ChangeRequestsPage />);
    expect(screen.getByText("Permission denied: change_requests:read required")).toBeTruthy();
    expect(screen.queryByText(/No change requests yet/)).toBeNull();
  });

  it("keeps showing the empty list when only a later refetch failed", () => {
    h.state = { data: { items: [] }, isLoading: false, error: new Error("network blip") };
    render(<ChangeRequestsPage />);
    expect(screen.queryByText("network blip")).toBeNull();
    expect(screen.getByText(/No change requests yet/)).toBeTruthy();
  });
});
