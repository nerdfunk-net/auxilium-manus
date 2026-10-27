import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AiGlossaryCard } from "./ai-glossary-card";

const h = vi.hoisted(() => ({ total: 3 as number | undefined }));

vi.mock("@/hooks/queries/use-ai-glossary-query", () => ({
  useAiGlossaryQuery: () => ({
    data: h.total === undefined ? undefined : { items: [], total: h.total },
  }),
}));
vi.mock("../dialogs/ai-glossary-dialog", () => ({
  AiGlossaryDialog: ({ open }: { open: boolean }) =>
    open ? <div>glossary dialog</div> : null,
}));

describe("AiGlossaryCard", () => {
  it("shows the term count and opens the glossary on demand", () => {
    h.total = 3;
    render(<AiGlossaryCard />);

    expect(screen.getByText(/3 terms defined/)).toBeTruthy();
    expect(screen.queryByText("glossary dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open glossary" }));
    expect(screen.getByText("glossary dialog")).toBeTruthy();
  });

  it("uses the singular and tolerates a missing count", () => {
    h.total = 1;
    const { unmount } = render(<AiGlossaryCard />);
    expect(screen.getByText(/1 term defined/)).toBeTruthy();
    unmount();

    h.total = undefined;
    render(<AiGlossaryCard />);
    expect(screen.queryByText(/defined/)).toBeNull();
  });
});
