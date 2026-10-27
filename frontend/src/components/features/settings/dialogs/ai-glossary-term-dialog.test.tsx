import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GlossaryTerm } from "@/components/features/ai-assistant/types/ai-assistant";

import {
  AiGlossaryTermDialog,
  aliasProblem,
  parseAliases,
} from "./ai-glossary-term-dialog";

const h = vi.hoisted(() => ({ create: vi.fn(), update: vi.fn() }));

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/hooks/queries/use-ai-glossary-mutations", () => ({
  useAiGlossaryMutations: () => ({
    createTerm: { mutate: h.create, isPending: false },
    updateTerm: { mutate: h.update, isPending: false },
  }),
}));
vi.mock("@/hooks/queries/use-get-nautobot-devices-field-values-query", () => ({
  useGetNautobotDevicesFieldValuesQuery: () => ({ data: undefined }),
}));

const EXISTING: GlossaryTerm = {
  id: 9,
  term: "core",
  aliases: ["backbone"],
  note: null,
  warnings: [],
  filter: {
    logic: "AND",
    conditions: [{ field: "role", operator: "equals", value: "Network" }],
    groups: [],
  },
};

function setup(term: GlossaryTerm | null = null, sourceIds: string[] = ["nb"]) {
  const onOpenChange = vi.fn();
  render(
    <AiGlossaryTermDialog
      open
      onOpenChange={onOpenChange}
      term={term}
      sourceIds={sourceIds}
    />,
  );
  return onOpenChange;
}

describe("AiGlossaryTermDialog", () => {
  beforeEach(() => {
    h.create.mockReset();
    h.update.mockReset();
  });

  it("parses comma separated aliases", () => {
    expect(parseAliases(" a, b c ,,d ")).toEqual(["a", "b c", "d"]);
  });

  it("checks aliases with the API's rules", () => {
    expect(aliasProblem("core", ["backbone", "spine"])).toBeNull();
    expect(aliasProblem("core", ["Core"])).toMatch(/used twice/);
    expect(aliasProblem("core", ["a", "A"])).toMatch(/used twice/);
    expect(aliasProblem("core", ["München"])).toMatch(/letters, digits/);
    expect(aliasProblem("core", ["x".repeat(65)])).toMatch(/64 characters/);
    expect(
      aliasProblem(
        "core",
        Array.from({ length: 11 }, (_, i) => `a${i}`),
      ),
    ).toMatch(/At most 10/);
  });

  it("shows a bad alias before anything is sent", async () => {
    setup();

    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: "dc" },
    });
    fireEvent.change(screen.getByLabelText("Aliases"), {
      target: { value: "data center, DC" },
    });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    expect(await screen.findByText(/"DC" is used twice/)).toBeTruthy();
    expect(h.create).not.toHaveBeenCalled();
  });

  it("lets the administrator pick the source the values are checked against", async () => {
    setup(null, ["lab", "prod"]);

    fireEvent.change(screen.getByLabelText("Nautobot source"), {
      target: { value: "prod" },
    });
    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: "dc" },
    });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    await waitFor(() => expect(h.create).toHaveBeenCalledTimes(1));
    expect(h.create.mock.calls[0][0].source_id).toBe("prod");
  });

  it("defaults to the first source and hides the picker for a single one", async () => {
    setup(null, ["lab"]);

    expect(screen.queryByLabelText("Nautobot source")).toBeNull();
    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: "dc" },
    });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    await waitFor(() => expect(h.create).toHaveBeenCalledTimes(1));
    expect(h.create.mock.calls[0][0].source_id).toBe("lab");
  });

  it("refuses a condition without a value", async () => {
    setup();

    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: "dc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    expect(
      await screen.findByText("Every condition needs a value"),
    ).toBeTruthy();
    expect(h.create).not.toHaveBeenCalled();
  });

  it("refuses a term with forbidden characters", async () => {
    setup();

    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: "a<b>" },
    });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    expect(await screen.findByText(/Use letters, digits/)).toBeTruthy();
    expect(h.create).not.toHaveBeenCalled();
  });

  it("creates a term with parsed aliases and the source id", async () => {
    setup();

    fireEvent.change(screen.getByLabelText("Term"), {
      target: { value: " dc " },
    });
    fireEvent.change(screen.getByLabelText("Aliases"), {
      target: { value: "data center, dc1" },
    });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), {
      target: { value: "Server" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    await waitFor(() => expect(h.create).toHaveBeenCalledTimes(1));
    expect(h.create.mock.calls[0][0]).toEqual({
      term: "dc",
      aliases: ["data center", "dc1"],
      note: null,
      source_id: "nb",
      filter: {
        logic: "AND",
        conditions: [{ field: "role", operator: "equals", value: "Server" }],
        groups: [],
      },
    });
  });

  it("updates the entry it was opened with", async () => {
    setup(EXISTING);

    fireEvent.change(screen.getByLabelText("Aliases"), {
      target: { value: "spine" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save term" }));

    await waitFor(() => expect(h.update).toHaveBeenCalledTimes(1));
    expect(h.update.mock.calls[0][0]).toMatchObject({
      id: 9,
      data: { term: "core", aliases: ["spine"], source_id: "nb" },
    });
    expect(h.create).not.toHaveBeenCalled();
  });

  it("adds and removes conditions and groups", async () => {
    setup(EXISTING);

    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    expect(screen.getByLabelText("Condition 2 value")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove condition 2" }));
    expect(screen.queryByLabelText("Condition 2 value")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Add group" }));
    expect(screen.getByLabelText("Exclude group 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove group 1" }));
    expect(screen.queryByLabelText("Exclude group 1")).toBeNull();
  });
});
