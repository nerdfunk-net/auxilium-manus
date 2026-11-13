import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportRunProposal } from "../types/ai-assistant";

const mutateAsync = vi.fn();
const mutationState = { isPending: false };
vi.mock("../hooks/use-report-generate-confirm", () => ({
  useReportGenerateConfirmMutation: () => ({ mutateAsync, ...mutationState }),
}));

const downloads = {
  pdf: { mutate: vi.fn(), isPending: false, isError: false, error: null },
  csv: { mutate: vi.fn(), isPending: false, isError: false, error: null },
};
vi.mock("@/hooks/queries/use-report-snapshot-download", () => ({
  useReportSnapshotDownload: (format: "pdf" | "csv") => downloads[format],
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function Viewer({ snapshotId }: { snapshotId: number }) {
      return <div data-testid="viewer">viewer {snapshotId}</div>;
    },
}));

import { ReportRunProposalCard } from "./report-run-proposal-card";

const NOW = 1_800_000_000;

function proposal(
  overrides: Partial<ReportRunProposal> = {},
): ReportRunProposal {
  return {
    kind: "report_run",
    summary: "Generate Serial numbers",
    token: "signed.token",
    expiresAt: NOW + 600,
    name: "Serial numbers",
    description: "All serials",
    template: null,
    sections: [
      {
        id: "s1",
        title: "Serials",
        source: "nautobot",
        dataset: "devices",
        presentation: "table",
      },
    ],
    state: "pending",
    ...overrides,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  mutateAsync.mockReset();
  mutationState.isPending = false;
  downloads.pdf.mutate.mockReset();
  downloads.csv.mutate.mockReset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ReportRunProposalCard", () => {
  it("shows the report, its sections and the layout", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({ template: { id: 4, name: "Inventory layout" } })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText("Serial numbers")).toBeTruthy();
    expect(screen.getByText("Serials")).toBeTruthy();
    expect(screen.getByText("nautobot/devices")).toBeTruthy();
    expect(screen.getByText(/Layout: Inventory layout/)).toBeTruthy();
  });

  it("shows text from the model as text, never as markup", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({ name: "<img src=x onerror=alert(1)>" })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeTruthy();
  });

  it("generates only on the click, with the signed token", async () => {
    const result = {
      snapshotId: 9,
      name: "Serial numbers - now",
      status: "complete",
      sectionsFailed: 0,
    };
    mutateAsync.mockResolvedValue(result);
    const onResult = vi.fn();
    render(
      <ReportRunProposalCard
        proposal={proposal()}
        onResult={onResult}
        onReject={vi.fn()}
      />,
    );
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(result));
    expect(mutateAsync).toHaveBeenCalledWith("signed.token");
  });

  it("shows the server's reason when generating fails, and can try again", async () => {
    mutateAsync.mockRejectedValue(new Error("Nautobot is not available"));
    render(
      <ReportRunProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));

    expect(await screen.findByText("Nautobot is not available")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /Generate/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("refuses an expired proposal without calling the server", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({ expiresAt: NOW - 1 })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText(/This proposal expired/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /Generate/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("waits while the assistant is still answering", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={vi.fn()}
        busy
      />,
    );

    expect(
      (screen.getByRole("button", { name: /Generate/ }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("rejecting generates nothing", () => {
    const onReject = vi.fn();
    render(
      <ReportRunProposalCard
        proposal={proposal()}
        onResult={vi.fn()}
        onReject={onReject}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));

    expect(onReject).toHaveBeenCalled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("offers open, PDF and CSV once generated", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({
          state: "applied",
          result: {
            snapshotId: 9,
            name: "Serial numbers - now",
            status: "complete",
            sectionsFailed: 0,
          },
        })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Generate/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /PDF/ }));
    fireEvent.click(screen.getByRole("button", { name: /Data \(CSV\)/ }));
    fireEvent.click(screen.getByRole("button", { name: /Open/ }));

    expect(downloads.pdf.mutate).toHaveBeenCalledWith(9);
    expect(downloads.csv.mutate).toHaveBeenCalledWith(9);
    expect(screen.getByTestId("viewer").textContent).toBe("viewer 9");
  });

  it("says when a section failed", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({
          state: "applied",
          result: {
            snapshotId: 9,
            name: "x",
            status: "partial",
            sectionsFailed: 2,
          },
        })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 sections/)).toBeTruthy();
  });

  it("warns when the layout failed even though every section succeeded", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({
          state: "applied",
          result: {
            snapshotId: 9,
            name: "x",
            status: "partial",
            sectionsFailed: 0,
          },
        })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText(/layout could not be applied/)).toBeTruthy();
  });

  it("shows no warning for a complete report", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({
          state: "applied",
          result: {
            snapshotId: 9,
            name: "x",
            status: "complete",
            sectionsFailed: 0,
          },
        })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.queryByText(/could not be/)).toBeNull();
  });

  it("says rejected proposals generated nothing", () => {
    render(
      <ReportRunProposalCard
        proposal={proposal({ state: "rejected" })}
        onResult={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText(/Nothing was generated/)).toBeTruthy();
  });
});
