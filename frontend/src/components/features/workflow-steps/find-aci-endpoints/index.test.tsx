import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FindAciEndpointsHelpPanel } from "./help-panel";
import { FindAciEndpointsPlugin } from "./index";

vi.mock("../shared/aci-source-select-dialog", () => ({
  AciSourceSelectDialog: ({
    open,
    onSave,
  }: {
    open: boolean;
    onSave: (id: string) => void;
  }) => (open ? <button onClick={() => onSave("lab")}>pick lab</button> : null),
}));

const { ConfigPanel } = FindAciEndpointsPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

describe("find-aci-endpoints config panel", () => {
  it("shows the defaults and the path the result lands at", () => {
    setup({});
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByDisplayValue("primary_ip4")).toBeTruthy();
    expect(screen.getByDisplayValue("aci_endpoint")).toBeTruthy();
    expect(screen.getByText(/parsed\.aci_endpoint\.endpoints\.parsed/)).toBeTruthy();
  });

  it("stores the chosen source and keeps the rest of the config", () => {
    const onChange = setup({ address_path: "primary_ip4" });
    fireEvent.click(screen.getByText("Configure Source"));
    fireEvent.click(screen.getByText("pick lab"));
    expect(onChange.mock.calls.at(-1)![0]).toEqual({
      address_path: "primary_ip4",
      aci_source_id: "lab",
    });
  });

  it("writes the address path and the output key", () => {
    const onChange = setup({ aci_source_id: "lab" });
    fireEvent.change(screen.getByDisplayValue("primary_ip4"), {
      target: { value: "custom.mac" },
    });
    expect(onChange.mock.calls.at(-1)![0].address_path).toBe("custom.mac");
    fireEvent.change(screen.getByDisplayValue("aci_endpoint"), { target: { value: "ep" } });
    expect(onChange.mock.calls.at(-1)![0].parsed_output_key).toBe("ep");
  });

  it("offers Edit Source once a source is set", () => {
    setup({ aci_source_id: "lab" });
    expect(screen.getByText("Edit Source")).toBeTruthy();
    expect(screen.getByText("lab")).toBeTruthy();
  });

  it("documents the result in the Help tab", () => {
    expect(FindAciEndpointsPlugin.HelpPanel).toBe(FindAciEndpointsHelpPanel);
    render(<FindAciEndpointsHelpPanel />);
    expect(screen.getAllByText("address_path").length).toBeGreaterThan(0);
    expect(screen.getAllByText("no_address").length).toBeGreaterThan(0);
  });
});
