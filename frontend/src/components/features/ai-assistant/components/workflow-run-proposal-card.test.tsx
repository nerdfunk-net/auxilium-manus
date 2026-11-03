import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunProposal } from "../types/ai-assistant";

const mutateAsync = vi.fn();
const mutationState = { isPending: false };
vi.mock("../hooks/use-workflow-run-confirm", () => ({
  useWorkflowRunConfirmMutation: () => ({ mutateAsync, ...mutationState }),
}));

import { WorkflowRunProposalCard } from "./workflow-run-proposal-card";

const NOW = 1_800_000_000;

function proposal(
  overrides: Partial<WorkflowRunProposal> = {},
): WorkflowRunProposal {
  return {
    kind: "workflow_run",
    summary: "Run PyATS Compare",
    token: "signed.token",
    expiresAt: NOW + 600,
    workflow: { id: 5, name: "PyATS Compare" },
    inputs: { features: "ospf", strict: true },
    devices: [{ id: "d1", name: "sw1" }],
    state: "pending",
    ...overrides,
  };
}

function renderCard(p: WorkflowRunProposal, busy = false) {
  const onResult = vi.fn();
  const onReject = vi.fn();
  const onAskResult = vi.fn();
  render(
    <WorkflowRunProposalCard
      proposal={p}
      onResult={onResult}
      onReject={onReject}
      onAskResult={onAskResult}
      busy={busy}
    />,
  );
  return { onResult, onReject, onAskResult };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  mutateAsync.mockReset();
  mutationState.isPending = false;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("WorkflowRunProposalCard", () => {
  it("shows the workflow, inputs and devices as text", () => {
    renderCard(proposal());

    expect(screen.getByText("PyATS Compare")).toBeTruthy();
    expect(screen.getByTestId("workflow-run-inputs").textContent).toContain(
      "features",
    );
    expect(screen.getByTestId("workflow-run-inputs").textContent).toContain(
      "ospf",
    );
    expect(screen.getByTestId("workflow-run-devices").textContent).toContain(
      "sw1",
    );
  });

  it("starts nothing until Run is clicked, then sends only the token", async () => {
    mutateAsync.mockResolvedValue({ runId: 42, workflowId: 5 });
    const { onResult } = renderCard(proposal());
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() =>
      expect(onResult).toHaveBeenCalledWith({ runId: 42, workflowId: 5 }),
    );
    expect(mutateAsync).toHaveBeenCalledWith("signed.token");
  });

  it("shows the server's error and does not report a result", async () => {
    mutateAsync.mockRejectedValue(
      new Error("This workflow is no longer released"),
    );
    const { onResult } = renderCard(proposal());

    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(
      await screen.findByText("This workflow is no longer released"),
    ).toBeTruthy();
    expect(onResult).not.toHaveBeenCalled();
  });

  it("disables Run once the proposal has expired", () => {
    renderCard(proposal({ expiresAt: NOW - 1 }));

    expect(screen.getByText(/expired/i)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("waits while the assistant is still answering", () => {
    renderCard(proposal(), true);

    expect(
      (screen.getByRole("button", { name: /run/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("rejecting reports it and a rejected card offers nothing to run", () => {
    const { onReject } = renderCard(proposal());
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalled();

    cleanup();
    renderCard(proposal({ state: "rejected" }));
    expect(screen.queryByRole("button", { name: /^run$/i })).toBeNull();
    expect(screen.getByText(/nothing was started/i)).toBeTruthy();
  });

  it("after the start shows the run id and lets the user ask for the result", () => {
    const { onAskResult } = renderCard(
      proposal({ state: "applied", result: { runId: 42, workflowId: 5 } }),
    );

    expect(screen.getByTestId("workflow-run-started").textContent).toContain(
      "run 42",
    );
    fireEvent.click(screen.getByRole("button", { name: /read the result/i }));
    expect(onAskResult).toHaveBeenCalledWith(
      { runId: 42, workflowId: 5 },
      "PyATS Compare",
    );
  });
});
