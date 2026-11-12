import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkflowNotesProposal } from "../types/ai-assistant";
import { WorkflowNotesProposalCard } from "./workflow-notes-proposal-card";

afterEach(cleanup);

const BEFORE = "# Backup\nruns nightly";
const AFTER = "# Backup\nruns nightly\n## Gotchas\nneeds SSH";

function proposal(
  overrides: Partial<WorkflowNotesProposal> = {},
): WorkflowNotesProposal {
  return {
    kind: "workflow_notes",
    workflowId: 4,
    summary: "Add gotchas",
    notes: AFTER,
    baseNotes: BEFORE,
    warnings: [],
    state: "pending",
    ...overrides,
  };
}

function setup(
  props: {
    proposal?: WorkflowNotesProposal;
    currentNotes?: string;
    onApply?: () => Promise<boolean>;
  } = {},
) {
  const onApply = props.onApply ?? vi.fn().mockResolvedValue(true);
  const onReject = vi.fn();
  render(
    <WorkflowNotesProposalCard
      proposal={props.proposal ?? proposal()}
      currentNotes={props.currentNotes ?? BEFORE}
      onApply={onApply}
      onReject={onReject}
    />,
  );
  return { onApply, onReject };
}

describe("WorkflowNotesProposalCard", () => {
  it("shows the summary and a diff against the saved notes", () => {
    setup();

    expect(screen.getByText("Add gotchas")).toBeTruthy();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(
      screen.getByLabelText("Proposed notes changes").textContent,
    ).toContain("needs SSH");
  });

  it("saves only when the user clicks, and never on render", async () => {
    const { onApply } = setup();
    expect(onApply).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /save notes/i }));

    await waitFor(() => expect(onApply).toHaveBeenCalledTimes(1));
  });

  it("calls reject without saving", () => {
    const { onApply, onReject } = setup();

    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("warns when the saved notes changed since the proposal", () => {
    setup({ currentNotes: "# Backup\nsomeone edited" });

    expect(screen.getByText(/saved notes changed/i)).toBeTruthy();
  });

  it("shows server warnings", () => {
    setup({ proposal: proposal({ warnings: ["looks like a credential"] }) });

    expect(screen.getByText("looks like a credential")).toBeTruthy();
  });

  it("re-enables the button after a failed save", async () => {
    const onApply = vi.fn().mockResolvedValue(false);
    setup({ onApply });

    const button = screen.getByRole("button", { name: /save notes/i });
    fireEvent.click(button);

    await waitFor(() => expect(onApply).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: /save notes/i,
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(false),
    );
  });

  it("has no buttons once applied or rejected", () => {
    setup({ proposal: proposal({ state: "applied" }) });

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Notes saved.")).toBeTruthy();
  });
});
