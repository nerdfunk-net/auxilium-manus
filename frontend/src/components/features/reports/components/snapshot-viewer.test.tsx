import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const snapshot = {
  data: undefined as unknown,
  isLoading: false,
  isError: false,
  error: null as Error | null,
};
vi.mock("@/hooks/queries/use-report-snapshots-query", () => ({
  useReportSnapshotQuery: () => snapshot,
}));
vi.mock("@/hooks/queries/use-report-definitions-query", () => ({
  useReportDefinitionQuery: () => ({ data: undefined }),
}));
vi.mock("@/hooks/queries/use-report-snapshot-download", () => ({
  useReportSnapshotDownload: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
}));
vi.mock("@/lib/auth-store", () => ({
  useAuthStore: (select: (state: { user: null }) => unknown) =>
    select({ user: null }),
}));
vi.mock("@/lib/permissions", () => ({ hasPermission: () => false }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("./send-snapshot-dialog", () => ({ SendSnapshotDialog: () => null }));

import { SnapshotViewer } from "./snapshot-viewer";

afterEach(() => {
  cleanup();
  snapshot.data = undefined;
  snapshot.isLoading = false;
  snapshot.isError = false;
  snapshot.error = null;
});

describe("SnapshotViewer", () => {
  it("shows the server's reason, not a loading text, when the snapshot is refused", () => {
    snapshot.isError = true;
    snapshot.error = new Error(
      "This report holds data from a source you may not read (sources.nautobot:read).",
    );

    render(<SnapshotViewer snapshotId={1} onClose={vi.fn()} />);

    expect(screen.getByText(/sources.nautobot:read/)).toBeTruthy();
    expect(screen.getByText("This snapshot cannot be shown.")).toBeTruthy();
    expect(screen.queryByText("Loading…")).toBeNull();
    expect(screen.queryByRole("button", { name: /PDF/ })).toBeNull();
  });

  it("says loading while the snapshot loads", () => {
    snapshot.isLoading = true;

    render(<SnapshotViewer snapshotId={1} onClose={vi.fn()} />);

    expect(screen.getByText("Loading…")).toBeTruthy();
  });

  it("offers PDF and CSV once the snapshot is there", () => {
    snapshot.data = {
      id: 1,
      name: "Serials",
      definition_id: null,
      generated_at: "2026-11-13T18:00:00Z",
      generated_by: "admin",
      status: "complete",
      content: { name: "Serials", description: null, sections: [], body: null },
    };

    render(<SnapshotViewer snapshotId={1} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: /PDF/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Data \(CSV\)/ })).toBeTruthy();
  });
});
