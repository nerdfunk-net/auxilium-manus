import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpdateNautobotVlanPlugin } from "./index";

vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: () => ({ isReady: true, isLoading: false, url: "http://nb" }),
}));
vi.mock("@/hooks/queries/use-nautobot-statuses-query", () => ({
  useNautobotStatusesQuery: () => ({
    data: [{ id: "1", name: "Active" }],
    isLoading: false,
  }),
}));
vi.mock("@/hooks/queries/use-get-nautobot-devices-field-values-query", () => ({
  useGetNautobotDevicesFieldValuesQuery: () => ({ data: undefined, isLoading: false }),
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
  const { ConfigPanel } = UpdateNautobotVlanPlugin;
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

const BASE = { nautobot_source_id: "nb", vid: "100" };

describe("UpdateNautobotVlan ConfigPanel", () => {
  it("warns when neither vlan_id nor vid is set", () => {
    renderPanel({ nautobot_source_id: "nb" });
    expect(screen.getByText("Set vlan_id or vid to select the VLAN.")).toBeTruthy();
  });

  it("asks for at least one field while none is filled in", () => {
    renderPanel(BASE);
    expect(screen.getByText("Fill in at least one field to update.")).toBeTruthy();
    expect(screen.queryByText("Set vlan_id or vid to select the VLAN.")).toBeNull();
  });

  it("drops the warning once a field is filled in", () => {
    renderPanel({ ...BASE, description: "clients" });
    expect(screen.queryByText("Fill in at least one field to update.")).toBeNull();
  });

  it("patches the config immutably when the name changes", () => {
    const config = { ...BASE };
    const onChange = renderPanel(config);
    fireEvent.change(screen.getByPlaceholderText("CLIENT-ACCESS"), {
      target: { value: "CLIENTS" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, name: "CLIENTS" });
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
});
