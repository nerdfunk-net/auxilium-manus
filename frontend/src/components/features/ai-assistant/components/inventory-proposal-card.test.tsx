import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InventoryProposal } from "../types/ai-assistant";
import { InventoryProposalCard } from "./inventory-proposal-card";

afterEach(cleanup);

function proposal(overrides: Partial<InventoryProposal> = {}): InventoryProposal {
  return {
    kind: "inventory",
    summary: "Active network devices in City A",
    totalCount: 12,
    warnings: [],
    baseFingerprint: "fp",
    state: "pending",
    tree: {
      type: "root",
      internalLogic: "AND",
      items: [
        { id: "1", field: "location", operator: "equals", value: "City A" },
        {
          id: "2",
          type: "group",
          logic: "NOT",
          internalLogic: "OR",
          items: [{ id: "3", field: "tag", operator: "equals", value: "lab" }],
        },
      ],
    },
    ...overrides,
  };
}

function renderCard(p: InventoryProposal, currentFingerprint = "fp") {
  const onApply = vi.fn();
  const onReject = vi.fn();
  render(
    <InventoryProposalCard
      proposal={p}
      currentFingerprint={currentFingerprint}
      onApply={onApply}
      onReject={onReject}
    />,
  );
  return { onApply, onReject };
}

describe("InventoryProposalCard", () => {
  it("shows the filter in words with the device count, and applies or rejects it", () => {
    const { onApply, onReject } = renderCard(proposal());

    expect(screen.getByText("Active network devices in City A")).toBeTruthy();
    expect(screen.getByText("12 devices")).toBeTruthy();
    expect(screen.getByText("location equals City A")).toBeTruthy();
    expect(screen.getByText(/NOT group, match OR/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /apply to builder/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onApply).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();
  });

  it("shows no count when it was not shared", () => {
    renderCard(proposal({ totalCount: null }));

    expect(screen.queryByText(/devices?$/)).toBeNull();
    expect(screen.getByRole("button", { name: /apply to builder/i })).toBeTruthy();
  });

  it("uses the singular for one device", () => {
    renderCard(proposal({ totalCount: 1 }));

    expect(screen.getByText("1 device")).toBeTruthy();
  });

  it("shows the warnings", () => {
    renderCard(proposal({ warnings: ["The values of role could not be verified."] }));

    expect(screen.getByText(/could not be verified/)).toBeTruthy();
  });

  it("warns when the builder changed after the proposal was made", () => {
    renderCard(proposal(), "other");

    expect(screen.getByText(/changed after this proposal/i)).toBeTruthy();
  });

  it("does not warn once decided, and hides the buttons", () => {
    renderCard(proposal({ state: "applied" }), "other");

    expect(screen.queryByText(/changed after this proposal/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
    expect(screen.getByText(/applied to the inventory builder/i)).toBeTruthy();
  });

  it("says rejected", () => {
    renderCard(proposal({ state: "rejected" }));

    expect(screen.getByText("Rejected.")).toBeTruthy();
  });
});
