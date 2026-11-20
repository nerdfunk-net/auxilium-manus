import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpdateNautobotPrefixPlugin } from "./index";

vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: () => ({
    isReady: true,
    isLoading: false,
    url: "http://nb",
  }),
}));
vi.mock("@/hooks/queries/use-nautobot-statuses-query", () => ({
  useNautobotStatusesQuery: () => ({
    data: [{ id: "1", name: "Active" }],
    isLoading: false,
  }),
}));
vi.mock("@/hooks/queries/use-get-nautobot-devices-field-values-query", () => ({
  useGetNautobotDevicesFieldValuesQuery: () => ({
    data: undefined,
    isLoading: false,
  }),
}));
vi.mock("../shared/nautobot-source-select-dialog", () => ({
  NautobotSourceSelectDialog: () => null,
}));
vi.mock("../shared/attribute-path-picker", () => ({
  AttributePathPicker: () => null,
}));

afterEach(cleanup);

function renderPanel(config: Record<string, unknown>) {
  const onChange = vi.fn();
  const { ConfigPanel } = UpdateNautobotPrefixPlugin;
  render(
    <ConfigPanel
      nodeId="n1"
      config={config}
      onChange={onChange}
      onPreview={() => undefined}
      workflowNodes={[]}
      workflowEdges={[]}
    />,
  );
  return onChange;
}

const BASE = { nautobot_source_id: "nb", prefix: "10.0.0.0/24" };

describe("UpdateNautobotPrefix ConfigPanel", () => {
  it("warns when neither prefix_id nor prefix is set", () => {
    renderPanel({ nautobot_source_id: "nb" });
    expect(
      screen.getByText("Set prefix_id or prefix to select the prefix."),
    ).toBeTruthy();
  });

  it("asks for at least one field while none is filled in", () => {
    renderPanel(BASE);
    expect(
      screen.getByText("Fill in at least one field to update."),
    ).toBeTruthy();
    expect(
      screen.queryByText("Set prefix_id or prefix to select the prefix."),
    ).toBeNull();
  });

  it("drops the warning once a field is filled in", () => {
    renderPanel({ ...BASE, description: "clients" });
    expect(
      screen.queryByText("Fill in at least one field to update."),
    ).toBeNull();
  });

  it("patches the config immutably when the role changes", () => {
    const config = { ...BASE };
    const onChange = renderPanel(config);
    fireEvent.change(screen.getByPlaceholderText("Management"), {
      target: { value: "CLIENTS" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, role: "CLIENTS" });
    expect(config).toEqual(BASE);
  });

  it("writes the locations as typed", () => {
    const onChange = renderPanel(BASE);
    fireEvent.change(screen.getByPlaceholderText("Berlin, Munich"), {
      target: { value: "Berlin" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, locations: "Berlin" });
  });

  it("shows replace as the default locations mode", () => {
    renderPanel(BASE);
    expect(screen.getByText("Replace – exact list")).toBeTruthy();
  });

  it("warns when the stored locations mode is not valid", () => {
    renderPanel({ ...BASE, status: "Active", locations_mode: "merge" });
    expect(screen.getByText(/stored mode is not valid/)).toBeTruthy();
    expect(screen.queryByText("Replace – exact list")).toBeNull();
  });

  it("switching on Prefixes from interfaces clears the prefix fields", () => {
    const onChange = renderPanel({ ...BASE, status: "Active" });
    fireEvent.click(
      screen.getByRole("switch", { name: "prefixes_from_interfaces" }),
    );
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        prefixes_from_interfaces: true,
        prefix: "",
        status: "",
        locations_mode: "add",
      }),
    );
  });

  it("in that mode shows the dry run switch and hides the prefix selector", () => {
    const onChange = renderPanel({
      nautobot_source_id: "nb",
      prefixes_from_interfaces: true,
    });
    expect(
      screen.queryByText("Set prefix_id or prefix to select the prefix."),
    ).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "dry_run" }));
    expect(onChange).toHaveBeenCalledWith({
      nautobot_source_id: "nb",
      prefixes_from_interfaces: true,
      dry_run: true,
    });
  });
});
