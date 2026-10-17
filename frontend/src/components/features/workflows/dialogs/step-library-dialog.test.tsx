import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PluginDefinition } from "../types/plugin-registry";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { StepLibraryDialog } from "./step-library-dialog";

vi.mock("@/hooks/queries/use-pyats-sources-query", () => ({
  usePyATSSourcesQuery: () => ({ data: { sources: [] } }),
}));
vi.mock("@/hooks/queries/use-batfish-sources-query", () => ({
  useBatfishSourcesQuery: () => ({ data: { sources: [] } }),
}));
vi.mock("@/hooks/queries/use-secret-manager-connections-query", () => ({
  useSecretManagerConnectionsQuery: () => ({ data: { connections: [] } }),
}));

function plugin(id: string, name: string, artifactType: string): PluginDefinition {
  return {
    id,
    name,
    overview: `${name} overview`,
    description: `${name} long description`,
    artifact_type: artifactType,
    directory: id,
    enabled: true,
    requires: [],
    produces: [],
    consumes: [],
    requires_parsed: [],
    produces_parsed: [],
    outcomes: [{ name: "success" }],
    metadata: { configuration_input: [] },
  };
}

const PLUGINS = [
  plugin("show-commands", "Show Commands", "command_execution"),
  plugin("label", "Label", "canvas_decoration"),
  plugin("pyats-run", "PyATS Run", "pyats"),
];

function renderDialog() {
  const onAddStep = vi.fn();
  const onAddStepAtPosition = vi.fn();
  render(
    <StepLibraryDialog
      isLoading={false}
      onAddStep={onAddStep}
      onAddStepAtPosition={onAddStepAtPosition}
      plugins={PLUGINS}
    />,
  );
  return { onAddStep, onAddStepAtPosition };
}

function openLibrary(position: { x: number; y: number } | null) {
  act(() => useWorkflowBuilderStore.getState().openStepLibrary(position));
}

beforeEach(() => {
  useWorkflowBuilderStore.getState().closeStepLibrary();
});
afterEach(cleanup);

describe("StepLibraryDialog", () => {
  it("renders nothing while closed", () => {
    renderDialog();
    expect(screen.queryByText("Steps library")).toBeNull();
  });

  it("filters by category, hides unconfigured sources, and shows the description of the selected step", () => {
    renderDialog();
    openLibrary(null);

    const nav = screen.getByRole("navigation", { name: "Step categories" });
    expect(within(nav).queryByText("PyATS")).toBeNull();
    fireEvent.click(within(nav).getByText("Command Execution"));

    expect(screen.queryByRole("button", { name: "Label" })).toBeNull();
    expect((screen.getByRole("button", { name: "Add" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Show Commands" }));
    expect(screen.getByText("Show Commands long description")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Add" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("adds at the stored drop position minus the per-kind offset and closes", () => {
    const { onAddStep, onAddStepAtPosition } = renderDialog();
    openLibrary({ x: 500, y: 300 });

    fireEvent.click(screen.getByRole("button", { name: "Show Commands" }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(onAddStepAtPosition).toHaveBeenCalledTimes(1);
    expect(onAddStepAtPosition.mock.calls[0][0].kind).toBe("show-commands");
    expect(onAddStepAtPosition.mock.calls[0][1]).toEqual({ x: 340, y: 236 });
    expect(onAddStep).not.toHaveBeenCalled();
    expect(useWorkflowBuilderStore.getState().stepLibrary).toEqual({ open: false, dropPosition: null });
  });

  it("falls back to the default placement for a plain click and adds on double-click", () => {
    const { onAddStep, onAddStepAtPosition } = renderDialog();
    openLibrary(null);

    fireEvent.doubleClick(screen.getByRole("button", { name: "Label" }));

    expect(onAddStep).toHaveBeenCalledTimes(1);
    expect(onAddStep.mock.calls[0][0].kind).toBe("label");
    expect(onAddStepAtPosition).not.toHaveBeenCalled();
  });

  it("filters by search text", () => {
    renderDialog();
    openLibrary(null);

    fireEvent.change(screen.getByLabelText("Search steps"), { target: { value: "label" } });
    expect(screen.getByRole("button", { name: "Label" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Show Commands" })).toBeNull();
  });

  it("shows the step details in a second modal without adding the step", () => {
    const { onAddStep, onAddStepAtPosition } = renderDialog();
    openLibrary(null);

    expect((screen.getByRole("button", { name: "Show step" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Show Commands" }));
    fireEvent.click(screen.getByRole("button", { name: "Show step" }));

    const details = screen.getAllByRole("dialog").at(-1) as HTMLElement;
    expect(within(details).getByText("Show Commands")).toBeTruthy();
    expect(within(details).getByText("Show Commands long description")).toBeTruthy();
    fireEvent.mouseDown(within(details).getByRole("tab", { name: "Help" }), { button: 0 });
    expect(within(details).getByText(/not available yet/i)).toBeTruthy();
    expect(onAddStep).not.toHaveBeenCalled();
    expect(onAddStepAtPosition).not.toHaveBeenCalled();
  });
});
