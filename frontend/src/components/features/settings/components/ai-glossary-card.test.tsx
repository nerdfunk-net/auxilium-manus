import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AiGlossaryCard } from "./ai-glossary-card";

const h = vi.hoisted(() => ({
  totals: { inventory_filter: 3, workflow_step: 2 } as Record<
    string,
    number | undefined
  >,
}));

vi.mock("@/hooks/queries/use-ai-glossary-query", () => ({
  useAiGlossaryQuery: ({ kind }: { kind: string }) => ({
    data:
      h.totals[kind] === undefined
        ? undefined
        : { items: [], total: h.totals[kind] },
  }),
}));
vi.mock("../dialogs/ai-glossary-dialog", () => ({
  AiGlossaryDialog: ({ open }: { open: boolean }) =>
    open ? <div>glossary dialog</div> : null,
}));

describe("AiGlossaryCard", () => {
  it("shows both counts and opens the glossary on demand", () => {
    h.totals = { inventory_filter: 3, workflow_step: 2 };
    render(<AiGlossaryCard />);

    expect(
      screen.getByText(/3 inventory terms and 2 step aliases defined/),
    ).toBeTruthy();
    expect(screen.queryByText("glossary dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open glossary" }));
    expect(screen.getByText("glossary dialog")).toBeTruthy();
  });

  it("uses the singular and tolerates a missing count", () => {
    h.totals = { inventory_filter: 1, workflow_step: 1 };
    const { unmount } = render(<AiGlossaryCard />);
    expect(
      screen.getByText(/1 inventory term and 1 step alias defined/),
    ).toBeTruthy();
    unmount();

    h.totals = { inventory_filter: undefined, workflow_step: 2 };
    render(<AiGlossaryCard />);
    expect(screen.queryByText(/defined/)).toBeNull();
  });
});
