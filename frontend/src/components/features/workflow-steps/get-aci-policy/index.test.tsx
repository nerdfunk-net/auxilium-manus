import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GetAciPolicyHelpPanel } from "./help-panel";
import { GetAciPolicyPlugin } from "./index";

const { ConfigPanel } = GetAciPolicyPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

describe("get-aci-policy config panel", () => {
  it("shows the default output key and the paths it produces", () => {
    setup({});
    expect(screen.getByDisplayValue("aci_policy")).toBeTruthy();
    expect(screen.getByText(/parsed\.aci_policy\.<epgs\|contracts\|l3outs>\.parsed/)).toBeTruthy();
  });

  it("writes the output key and keeps the rest of the config", () => {
    const onChange = setup({ parsed_output_key: "aci_policy", other: 1 });
    fireEvent.change(screen.getByDisplayValue("aci_policy"), { target: { value: "pol" } });
    expect(onChange.mock.calls.at(-1)![0]).toEqual({ parsed_output_key: "pol", other: 1 });
  });

  it("documents both result entries in the Help tab", () => {
    expect(GetAciPolicyPlugin.HelpPanel).toBe(GetAciPolicyHelpPanel);
    render(<GetAciPolicyHelpPanel />);
    expect(screen.getAllByText("epgs").length).toBeGreaterThan(0);
    expect(screen.getAllByText("contracts").length).toBeGreaterThan(0);
  });
});
