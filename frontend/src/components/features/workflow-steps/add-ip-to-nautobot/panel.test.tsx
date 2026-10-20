import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddIpToNautobotPlugin } from "./index";

vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: () => ({ isReady: true, isLoading: false, url: "http://nb" }),
}));
vi.mock("@/hooks/queries/use-nautobot-statuses-query", () => ({
  useNautobotStatusesQuery: () => ({
    data: [
      { id: "1", name: "Active" },
      { id: "2", name: "Deprecated" },
      { id: "3", name: "Reserved" },
    ],
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
  const { ConfigPanel } = AddIpToNautobotPlugin;
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

const BASE = { nautobot_source_id: "nb", ip_address: "{custom.new_ip}" };

describe("AddIpToNautobot ConfigPanel", () => {
  it("warns when the ip_address is missing", () => {
    renderPanel({ nautobot_source_id: "nb" });
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });

  it("shows the default prefix length only when create_prefix is on", () => {
    renderPanel(BASE);
    expect(screen.queryByLabelText("Default prefix length")).toBeNull();
    cleanup();
    renderPanel({ ...BASE, create_prefix: true });
    expect(screen.getByLabelText("Default prefix length")).toBeTruthy();
  });

  it("warns about an invalid prefix length", () => {
    renderPanel({ ...BASE, create_prefix: true, default_mask_length: 200 });
    expect(screen.getByText("Enter a length from 1 to 128.")).toBeTruthy();
  });

  it("warns when set_primary has no interface", () => {
    renderPanel({ ...BASE, set_primary: true });
    expect(screen.getByText("set_primary needs interface_name.")).toBeTruthy();
  });

  it("patches the config immutably when the namespace changes", () => {
    const config = { ...BASE };
    const onChange = renderPanel(config);
    fireEvent.change(screen.getByDisplayValue("Global"), { target: { value: "Lab" } });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, namespace: "Lab" });
    expect(config).toEqual(BASE);
  });

  it("writes a whole number as a number into default_mask_length", () => {
    const onChange = renderPanel({ ...BASE, create_prefix: true });
    fireEvent.change(screen.getByLabelText("Default prefix length"), {
      target: { value: "26" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, create_prefix: true, default_mask_length: 26 });
  });
});
