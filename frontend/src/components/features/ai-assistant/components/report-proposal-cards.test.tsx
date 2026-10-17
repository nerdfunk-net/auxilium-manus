import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportOutlineProposal, SectionTextProposal } from "../types/ai-assistant";
import { ReportOutlineCard, SectionTextCard } from "./report-proposal-cards";

afterEach(cleanup);

function outline(state: ReportOutlineProposal["state"] = "pending"): ReportOutlineProposal {
  return {
    kind: "report_outline",
    summary: "Fleet overview",
    name: "Fleet",
    description: null,
    state,
    sections: [
      {
        id: "s1",
        title: "Per site",
        presentation: "bar",
        text: "Devices per site",
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
      },
    ],
  };
}

function sectionText(state: SectionTextProposal["state"] = "pending"): SectionTextProposal {
  return {
    kind: "section_text",
    summary: "Shorter wording",
    reportId: 1,
    sectionId: "s1",
    sectionTitle: "Per site",
    text: "Most sites have two switches.",
    state,
  };
}

describe("ReportOutlineCard", () => {
  it("lists the sections and applies or rejects", () => {
    const onApply = vi.fn();
    const onReject = vi.fn();
    render(<ReportOutlineCard proposal={outline()} onApply={onApply} onReject={onReject} />);

    expect(screen.getByText("Per site")).toBeTruthy();
    expect(screen.getByText("Group by: location")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /open in report editor/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));

    expect(onApply).toHaveBeenCalledOnce();
    expect(onReject).toHaveBeenCalledOnce();
  });

  it("hides the buttons once applied", () => {
    render(<ReportOutlineCard proposal={outline("applied")} onApply={vi.fn()} onReject={vi.fn()} />);

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/opened in the report editor/i)).toBeTruthy();
  });
});

describe("SectionTextCard", () => {
  it("shows the section and the new text", () => {
    const onApply = vi.fn();
    render(<SectionTextCard proposal={sectionText()} onApply={onApply} onReject={vi.fn()} />);

    expect(screen.getByText("Section: Per site")).toBeTruthy();
    expect(screen.getByText("Most sites have two switches.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /open in report editor/i }));
    expect(onApply).toHaveBeenCalledOnce();
  });

  it("shows the rejected state", () => {
    render(<SectionTextCard proposal={sectionText("rejected")} onApply={vi.fn()} onReject={vi.fn()} />);

    expect(screen.getByText("Rejected.")).toBeTruthy();
  });
});
