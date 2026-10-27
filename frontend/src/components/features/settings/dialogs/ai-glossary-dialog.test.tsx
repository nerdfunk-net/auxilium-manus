import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GlossaryFilter } from "@/components/features/ai-assistant/types/ai-assistant";

import { AiGlossaryDialog, summarizeFilter } from "./ai-glossary-dialog";

const h = vi.hoisted(() => ({
  query: vi.fn(),
  remove: vi.fn(),
  sources: {
    value: [{ source_id: "nb", url: "x", token_configured: true }] as unknown,
  },
}));

vi.mock("@/hooks/queries/use-ai-glossary-query", () => ({
  useAiGlossaryQuery: (options: unknown) => h.query(options),
}));
vi.mock("@/hooks/queries/use-ai-glossary-mutations", () => ({
  useAiGlossaryMutations: () => ({
    deleteTerm: { mutate: h.remove, isPending: false },
  }),
}));
vi.mock("@/hooks/queries/use-nautobot-configured-sources-query", () => ({
  useNautobotConfiguredSourcesQuery: () => ({ data: h.sources.value }),
}));
vi.mock("./ai-glossary-term-dialog", () => ({
  AiGlossaryTermDialog: ({
    open,
    term,
    sourceIds,
  }: {
    open: boolean;
    term: { term: string } | null;
    sourceIds: string[];
  }) =>
    open ? (
      <div>{`term dialog: ${term?.term ?? "new"} (${sourceIds.join("+")})`}</div>
    ) : null,
}));

const FILTER: GlossaryFilter = {
  logic: "AND",
  conditions: [{ field: "role", operator: "equals", value: "Network" }],
  groups: [
    {
      logic: "OR",
      negate: true,
      conditions: [{ field: "name", operator: "contains", value: "lab" }],
    },
  ],
};
const ROW = {
  id: 4,
  term: "core",
  aliases: ["backbone"],
  filter: FILTER,
  note: null,
  warnings: [],
};

function result(items = [ROW], total = items.length) {
  return { data: { items, total }, isLoading: false, error: null };
}

describe("summarizeFilter", () => {
  it("renders conditions and negated groups on one line", () => {
    expect(summarizeFilter(FILTER)).toBe(
      "role equals Network AND NOT (name contains lab)",
    );
  });
});

describe("AiGlossaryDialog", () => {
  beforeEach(() => {
    h.query.mockReset();
    h.remove.mockReset();
    h.sources.value = [{ source_id: "nb", url: "x", token_configured: true }];
    h.query.mockReturnValue(result());
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("only queries while open", () => {
    render(<AiGlossaryDialog open={false} onOpenChange={vi.fn()} />);

    expect(h.query).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false }),
    );
  });

  it("lists terms with their aliases and filter", () => {
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    expect(screen.getByText("core")).toBeTruthy();
    expect(screen.getByText("backbone")).toBeTruthy();
    expect(
      screen.getByText("role equals Network AND NOT (name contains lab)"),
    ).toBeTruthy();
    expect(screen.getByText("1-1 of 1")).toBeTruthy();
  });

  it("searches after a pause and starts again at the first page", () => {
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Search glossary"), {
      target: { value: " dc " },
    });
    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(h.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "dc", offset: 0, limit: 25 }),
    );
  });

  it("pages through a long list", () => {
    h.query.mockReturnValue(result([ROW], 60));
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(h.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 25 }),
    );
  });

  it("offers every source with a token to the form", () => {
    h.sources.value = [
      { source_id: "lab", url: "x", token_configured: true },
      { source_id: "dead", url: "x", token_configured: false },
      { source_id: "prod", url: "x", token_configured: true },
    ];
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Add term" }));

    expect(screen.getByText("term dialog: new (lab+prod)")).toBeTruthy();
  });

  it("steps back a page when the last row of a later page is deleted", () => {
    h.remove.mockImplementation((_id, options) => options.onSuccess());
    h.query.mockReturnValue(result([ROW], 26));
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(h.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 25 }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete core" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(h.query).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0 }),
    );
  });

  it("opens the form to add and to edit", () => {
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Add term" }));
    expect(screen.getByText("term dialog: new (nb)")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Edit core" }));
    expect(screen.getByText("term dialog: core (nb)")).toBeTruthy();
  });

  it("asks before deleting", () => {
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete core" }));
    expect(h.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(h.remove.mock.calls[0][0]).toBe(4);
  });

  it("cannot add or edit without a usable Nautobot source", () => {
    h.sources.value = [];
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    expect(
      (screen.getByRole("button", { name: "Add term" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText(/Configure a Nautobot source first/)).toBeTruthy();
  });

  it("says so when nothing matches", () => {
    h.query.mockReturnValue(result([], 0));
    render(<AiGlossaryDialog open onOpenChange={vi.fn()} />);

    expect(screen.getByText("No glossary terms yet.")).toBeTruthy();
  });
});
