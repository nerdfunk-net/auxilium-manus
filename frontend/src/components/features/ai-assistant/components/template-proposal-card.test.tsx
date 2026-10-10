import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProposalState, TemplateProposal } from "../types/ai-assistant";
import { TemplateProposalCard } from "./template-proposal-card";

afterEach(cleanup);

const BEFORE = "hostname a\nntp 1.1.1.1";
const AFTER = "hostname a\nntp 2.2.2.2\nlogging on";

function proposal(overrides: Partial<TemplateProposal> = {}): TemplateProposal {
  return {
    kind: "template",
    content: AFTER,
    summary: "Change NTP",
    warnings: [],
    baseContent: BEFORE,
    state: "pending",
    ...overrides,
  };
}

function setup(
  props: {
    proposal?: TemplateProposal;
    currentContent?: string;
  } = {},
) {
  const onApply = vi.fn();
  const onReject = vi.fn();
  const view = render(
    <TemplateProposalCard
      proposal={props.proposal ?? proposal()}
      currentContent={props.currentContent ?? BEFORE}
      onApply={onApply}
      onReject={onReject}
    />,
  );
  return { onApply, onReject, ...view };
}

describe("TemplateProposalCard", () => {
  it("shows the summary and a diff against the current editor content", () => {
    setup();

    expect(screen.getByText("Change NTP")).toBeTruthy();
    expect(screen.getByText("+2")).toBeTruthy();
    expect(screen.getByText("-1")).toBeTruthy();
    const diff = screen.getByLabelText("Proposed changes").textContent ?? "";
    expect(diff).toContain("ntp 2.2.2.2");
    expect(diff).toContain("ntp 1.1.1.1");
  });

  it("applies and rejects through its buttons while pending", () => {
    const { onApply, onReject } = setup();

    fireEvent.click(screen.getByRole("button", { name: /apply to editor/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("does not warn while the editor still matches the proposal's base", () => {
    setup();

    expect(
      screen.queryByText(/editor changed after this proposal/i),
    ).toBeNull();
  });

  it("warns that applying overwrites edits made after the proposal", () => {
    setup({ currentContent: `${BEFORE}\nmy own edit` });

    expect(
      screen.getByText(/editor changed after this proposal/i),
    ).toBeTruthy();
    // The diff is against what the user sees now, not against the stale base.
    expect(screen.getByLabelText("Proposed changes").textContent).toContain(
      "my own edit",
    );
  });

  it("shows the server's warnings", () => {
    setup({ proposal: proposal({ warnings: ["Trial render raised: boom"] }) });

    expect(screen.getByText("Trial render raised: boom")).toBeTruthy();
  });

  it.each<[ProposalState, RegExp]>([
    ["applied", /applied to the editor/i],
    ["rejected", /^rejected\.$/i],
  ])("is final once %s: no buttons and no stale warning", (state, text) => {
    setup({
      proposal: proposal({ state }),
      currentContent: "something else entirely",
    });

    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.queryByText(/editor changed after this proposal/i),
    ).toBeNull();
    expect(screen.getByText(text)).toBeTruthy();
  });
});
