import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RemoveFromNautobotPlugin } from "./index";

vi.mock("@/hooks/queries/use-nautobot-source-credentials", () => ({
  useNautobotSourceCredentials: () => ({ isReady: true, isLoading: false, url: "http://nb" }),
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
  const { ConfigPanel } = RemoveFromNautobotPlugin;
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

const BASE = { nautobot_source_id: "nb", device_id: "{device.id}" };

describe("RemoveFromNautobot ConfigPanel", () => {
  it("warns when the device_id is missing", () => {
    renderPanel({ nautobot_source_id: "nb" });
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
  });

  it("has the IP checkbox off by default and still warns that the removal is permanent", () => {
    renderPanel(BASE);
    const box = screen.getByRole("checkbox");
    expect(box.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("The device and its interfaces are deleted permanently.")).toBeTruthy();
  });

  it("stores a real boolean when the checkbox is ticked", () => {
    const onChange = renderPanel(BASE);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith({ ...BASE, remove_ip_addresses: true });
  });

  it("shows the permanence warning when IP removal is on", () => {
    renderPanel({ ...BASE, remove_ip_addresses: true });
    expect(screen.getByText(/exclusive IP addresses are deleted permanently/)).toBeTruthy();
  });
});
