import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { QueryProposal } from "../types/ai-assistant";
import { QueryProposalCard } from "./query-proposal-card";

afterEach(cleanup);

function proposal(state: QueryProposal["state"] = "pending"): QueryProposal {
  return {
    kind: "query",
    summary: "Devices per site",
    state,
    query: {
      source: "report_data",
      dataset: "inventory",
      scope: { kind: "latest" },
      filters: [],
      group_by: ["location"],
      metrics: [{ op: "count", alias: "devices" }],
      select: [],
      order_by: [],
      limit: 500,
    },
  };
}

describe("QueryProposalCard", () => {
  it("shows the query in words and applies or rejects it", () => {
    const onApply = vi.fn();
    const onReject = vi.fn();
    render(<QueryProposalCard proposal={proposal()} onApply={onApply} onReject={onReject} />);

    expect(screen.getByText("Devices per site")).toBeTruthy();
    expect(screen.getByText("Group by: location")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /apply to explore/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onApply).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();
  });

  it("hides the buttons once decided", () => {
    render(<QueryProposalCard proposal={proposal("applied")} onApply={vi.fn()} onReject={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
    expect(screen.getByText(/applied to the query builder/i)).toBeTruthy();
  });
});
