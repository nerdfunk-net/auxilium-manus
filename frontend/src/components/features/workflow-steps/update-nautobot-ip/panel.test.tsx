import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UpdateNautobotIpPlugin } from "./index";

vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: () => ({ isReady: true, isLoading: false, url: "http://nb" }),
}));
vi.mock("@/hooks/queries/use-nautobot-statuses-query", () => ({
  useNautobotStatusesQuery: () => ({
    data: [
      { id: "1", name: "Active" },
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
  const { ConfigPanel } = UpdateNautobotIpPlugin;
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

const BASE = { nautobot_source_id: "nb", ip_id: "{custom.ip_id}" };

describe("UpdateNautobotIp ConfigPanel", () => {
  it("warns when the ip_id is missing", () => {
    renderPanel({ nautobot_source_id: "nb" });
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });

  it("asks for at least one field while none is filled in", () => {
    renderPanel(BASE);
    expect(screen.getByText("Fill in at least one field to update.")).toBeTruthy();
  });

  it("drops the warning once a field is filled in", () => {
    renderPanel({ ...BASE, description: "moved" });
    expect(screen.queryByText("Fill in at least one field to update.")).toBeNull();
  });

  it("patches the config immutably when the DNS name changes", () => {
    const config = { ...BASE };
    const onChange = renderPanel(config);
    fireEvent.change(screen.getByPlaceholderText("host.example.org"), {
      target: { value: "a.example.org" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, dns_name: "a.example.org" });
    expect(config).toEqual(BASE);
  });

  it("writes the role as typed", () => {
    const onChange = renderPanel(BASE);
    fireEvent.change(screen.getByPlaceholderText("Secondary"), { target: { value: "Primary" } });
    expect(onChange).toHaveBeenCalledWith({ ...BASE, role: "Primary" });
  });
});
