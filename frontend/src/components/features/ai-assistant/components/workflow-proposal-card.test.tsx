import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ProposalState,
  WorkflowChanges,
  WorkflowProposal,
} from "../types/ai-assistant";
import { WorkflowProposalCard } from "./workflow-proposal-card";

afterEach(cleanup);

const NO_CHANGES: WorkflowChanges = {
  nodes_added: [],
  nodes_removed: [],
  nodes_changed: [],
  edges_added: [],
  edges_removed: [],
  static_attributes_changed: false,
};

function proposal(
  changes: Partial<WorkflowChanges> = {},
  overrides: Partial<WorkflowProposal> = {},
): WorkflowProposal {
  return {
    kind: "workflow",
    summary: "Back up configs",
    canvas_nodes: [],
    canvas_edges: [],
    canvas_groups: [],
    static_attributes: [],
    changes: { ...NO_CHANGES, ...changes },
    warnings: [],
    baseFingerprint: "fp-1",
    state: "pending",
    ...overrides,
  };
}

function setup(p: WorkflowProposal, currentFingerprint = "fp-1") {
  const onApply = vi.fn();
  const onReject = vi.fn();
  render(
    <WorkflowProposalCard
      proposal={p}
      currentFingerprint={currentFingerprint}
      onApply={onApply}
      onReject={onReject}
    />,
  );
  return { onApply, onReject };
}

describe("WorkflowProposalCard", () => {
  it("lists added, removed and changed steps and edges and counts them", () => {
    setup(
      proposal({
        nodes_added: [
          { id: "n1", kind: "get-nautobot-devices", title: "Devices" },
        ],
        nodes_removed: [{ id: "n2", kind: "show-commands", title: "Old show" }],
        nodes_changed: [
          {
            id: "n3",
            kind: "notify",
            title: "Notify",
            fields: ["message"],
            before: '{\n  "message": "a"\n}',
            after: '{\n  "message": "b"\n}',
          },
        ],
        edges_added: [{ from: "n1", outcome: "success", to: "n3" }],
        edges_removed: [{ from: "n2", outcome: "failure", to: "n3" }],
        static_attributes_changed: true,
      }),
    );

    expect(screen.getByText("Back up configs")).toBeTruthy();
    expect(screen.getByText("5 changes")).toBeTruthy();
    expect(screen.getByText("Devices")).toBeTruthy();
    expect(screen.getByText(/\(get-nautobot-devices\) added/)).toBeTruthy();
    expect(screen.getByText("Old show")).toBeTruthy();
    expect(screen.getByText(/\(show-commands\) removed/)).toBeTruthy();
    expect(screen.getByText(/\(notify\) — message/)).toBeTruthy();
    expect(screen.getByText("n1 —success→ n3")).toBeTruthy();
    expect(screen.getByText("n2 —failure→ n3")).toBeTruthy();
    expect(
      screen.getByText(/run inputs \(static attributes\) changed/i),
    ).toBeTruthy();
  });

  it("uses the singular for one change", () => {
    setup(
      proposal({ edges_added: [{ from: "a", outcome: "success", to: "b" }] }),
    );

    expect(screen.getByText("1 change")).toBeTruthy();
  });

  it("shows the (masked) configuration of an added step", () => {
    setup(
      proposal({
        nodes_added: [
          {
            id: "n1",
            kind: "notify",
            title: "Notify",
            config: '{\n  "token": "***REDACTED***"\n}',
          },
        ],
      }),
    );

    expect(screen.getByText("Configuration")).toBeTruthy();
    expect(document.body.textContent).toContain("***REDACTED***");
  });

  it("offers no configuration for an added step without any", () => {
    setup(
      proposal({
        nodes_added: [
          { id: "f", kind: "funnel", title: "Funnel", config: "{}" },
        ],
      }),
    );

    expect(screen.queryByText("Configuration")).toBeNull();
  });

  it("shows the line diff of a changed step", () => {
    setup(
      proposal({
        nodes_changed: [
          {
            id: "n3",
            kind: "notify",
            title: "Notify",
            fields: ["message"],
            before: '{\n  "message": "old text"\n}',
            after: '{\n  "message": "new text"\n}',
          },
        ],
      }),
    );

    const text = document.body.textContent ?? "";
    expect(text).toContain("old text");
    expect(text).toContain("new text");
  });

  it("shows the server's validation warnings with their step", () => {
    setup(
      proposal(
        {},
        {
          warnings: [
            { node_id: "n1", code: "w", message: "No credential chosen" },
          ],
        },
      ),
    );

    expect(screen.getByText(/n1: No credential chosen/)).toBeTruthy();
  });

  it("applies and rejects through its buttons while pending", () => {
    const { onApply, onReject } = setup(proposal());

    fireEvent.click(screen.getByRole("button", { name: /apply to canvas/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("does not warn while the canvas still matches the proposal's base", () => {
    setup(proposal());

    expect(
      screen.queryByText(/canvas changed after this proposal/i),
    ).toBeNull();
  });

  it("warns that applying replaces edits made after the proposal", () => {
    setup(proposal(), "fp-2");

    expect(
      screen.getByText(/canvas changed after this proposal/i),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /apply to canvas/i }),
    ).toBeTruthy();
  });

  it.each<[ProposalState, RegExp]>([
    ["applied", /applied to the canvas/i],
    ["rejected", /^rejected\.$/i],
  ])("is final once %s: no buttons and no stale warning", (state, text) => {
    setup(proposal({}, { state }), "fp-changed");

    expect(screen.queryByRole("button")).toBeNull();
    expect(
      screen.queryByText(/canvas changed after this proposal/i),
    ).toBeNull();
    expect(screen.getByText(text)).toBeTruthy();
  });
});
