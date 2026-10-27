import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  GlossaryKind,
  GlossaryTerm,
} from "@/components/features/ai-assistant/types/ai-assistant";

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
vi.mock("@/components/ui/combobox", () => ({
  Combobox: ({
    options,
    value,
    onValueChange,
  }: {
    options: { value: string; label: string }[];
    value: string;
    onValueChange: (value: string) => void;
  }) => (
    <select
      aria-label="Step"
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
    >
      <option value="">none</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("@/hooks/queries/use-workflow-steps-query", () => ({
  useWorkflowStepsQuery: () => ({
    data: {
      plugins: [
        {
          id: "get-git-devices",
          name: "Get from Git",
          enabled: true,
          executable: true,
        },
        { id: "off-step", name: "Off", enabled: false, executable: true },
        { id: "decor", name: "Decor", enabled: true, executable: false },
      ],
    },
  }),
}));
vi.mock("@/hooks/queries/use-get-nautobot-devices-field-values-query", () => ({
  useGetNautobotDevicesFieldValuesQuery: () => ({ data: undefined }),
}));

const EXISTING: GlossaryTerm = {
  id: 9,
  kind: "inventory_filter",
  term: "core",
  aliases: ["backbone"],
  note: null,
  warnings: [],
  payload: {
    logic: "AND",
    conditions: [{ field: "role", operator: "equals", value: "Network" }],
    groups: [],
  },
};

const ALIAS: GlossaryTerm = {
  id: 4,
  kind: "workflow_step",
  term: "git devices",
  aliases: [],
  note: null,
  warnings: [],
  payload: { step_id: "get-git-devices" },
};

function setup(
  term: GlossaryTerm | null = null,
  sourceIds: string[] = ["nb"],
  kind: GlossaryKind = term?.kind ?? "inventory_filter",
) {
  const onOpenChange = vi.fn();
  render(
    <AiGlossaryTermDialog
      open
      onOpenChange={onOpenChange}
      kind={kind}
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
      kind: "inventory_filter",
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

  describe("workflow step aliases", () => {
    it("offers enabled executable steps and hides the filter and source", () => {
      setup(null, ["nb"], "workflow_step");

      expect(
        screen.getByRole("option", { name: "Get from Git (get-git-devices)" }),
      ).toBeTruthy();
      expect(screen.queryByRole("option", { name: /Off/ })).toBeNull();
      expect(screen.queryByRole("option", { name: /Decor/ })).toBeNull();
      expect(screen.queryByLabelText("Condition 1 value")).toBeNull();
      expect(screen.queryByLabelText("Nautobot source")).toBeNull();
    });

    it("needs a step", async () => {
      setup(null, [], "workflow_step");

      fireEvent.change(screen.getByLabelText("Term"), {
        target: { value: "git devices" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save term" }));

      expect(await screen.findByText("Choose a step")).toBeTruthy();
      expect(h.create).not.toHaveBeenCalled();
    });

    it("creates an alias without a Nautobot source", async () => {
      setup(null, [], "workflow_step");

      fireEvent.change(screen.getByLabelText("Term"), {
        target: { value: "git devices" },
      });
      fireEvent.change(screen.getByLabelText("Aliases"), {
        target: { value: "from git" },
      });
      fireEvent.change(screen.getByLabelText("Step"), {
        target: { value: "get-git-devices" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save term" }));

      await waitFor(() => expect(h.create).toHaveBeenCalledTimes(1));
      expect(h.create.mock.calls[0][0]).toEqual({
        kind: "workflow_step",
        term: "git devices",
        aliases: ["from git"],
        note: null,
        step_id: "get-git-devices",
      });
    });

    it("edits an existing alias", async () => {
      setup(ALIAS);

      expect((screen.getByLabelText("Step") as HTMLSelectElement).value).toBe(
        "get-git-devices",
      );
      fireEvent.change(screen.getByLabelText("Aliases"), {
        target: { value: "gd" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save term" }));

      await waitFor(() => expect(h.update).toHaveBeenCalledTimes(1));
      expect(h.update.mock.calls[0][0]).toMatchObject({
        id: 4,
        data: {
          kind: "workflow_step",
          aliases: ["gd"],
          step_id: "get-git-devices",
        },
      });
    });
  });
});
