import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompareAciSubnetsHelpPanel } from "./help-panel";
import { CompareAciSubnetsPlugin } from "./index";

vi.mock("../shared/aci-source-select-dialog", () => ({
  AciSourceSelectDialog: ({ open, onSave }: { open: boolean; onSave: (id: string) => void }) =>
    open ? <button onClick={() => onSave("lab")}>pick aci</button> : null,
}));
vi.mock("../shared/nautobot-source-select-dialog", () => ({
  NautobotSourceSelectDialog: ({
    open,
    onSave,
  }: {
    open: boolean;
    onSave: (id: string) => void;
  }) => (open ? <button onClick={() => onSave("nb")}>pick nautobot</button> : null),
}));

const { ConfigPanel } = CompareAciSubnetsPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

function last(onChange: ReturnType<typeof setup>): Config {
  return onChange.mock.calls.at(-1)![0];
}

describe("compare-aci-subnets config panel", () => {
  it("shows both sources unconfigured and the defaults", () => {
    setup({});
    expect(screen.getAllByText("Not configured")).toHaveLength(2);
    expect(screen.getByDisplayValue("Global")).toBeTruthy();
    expect(screen.getByDisplayValue("aci_subnet_report")).toBeTruthy();
  });

  it("stores each chosen source under its own key", () => {
    const onChange = setup({});
    fireEvent.click(screen.getAllByText("Configure Source")[0]!);
    fireEvent.click(screen.getByText("pick aci"));
    expect(last(onChange)).toEqual({ aci_source_id: "lab" });
    fireEvent.click(screen.getAllByText("Configure Source")[1]!);
    fireEvent.click(screen.getByText("pick nautobot"));
    expect(last(onChange)).toEqual({ nautobot_source_id: "nb" });
  });

  it("writes the namespace, the VRF switch, the scope lines and the output key", () => {
    const onChange = setup({ aci_source_id: "lab" });
    fireEvent.change(screen.getByDisplayValue("Global"), { target: { value: "Heroes" } });
    expect(last(onChange)).toMatchObject({ namespace: "Heroes", aci_source_id: "lab" });
    fireEvent.click(screen.getByRole("switch"));
    expect(last(onChange).namespace_from_vrf).toBe(true);
    fireEvent.change(screen.getByPlaceholderText("10.0.0.0/8"), {
      target: { value: "10.0.0.0/8\n172.16.0.0/12" },
    });
    expect(last(onChange).scope_prefixes).toEqual(["10.0.0.0/8", "172.16.0.0/12"]);
    fireEvent.change(screen.getByDisplayValue("aci_subnet_report"), { target: { value: "drift" } });
    expect(last(onChange).output_key).toBe("drift");
  });

  it("disables the namespace field while the VRF name is used", () => {
    setup({ namespace_from_vrf: true });
    expect((screen.getByDisplayValue("Global") as HTMLInputElement).disabled).toBe(true);
  });

  it("lists the scope prefixes one per line", () => {
    setup({ scope_prefixes: ["10.0.0.0/8", "172.16.0.0/12"] });
    expect((screen.getByPlaceholderText("10.0.0.0/8") as HTMLTextAreaElement).value).toBe(
      "10.0.0.0/8\n172.16.0.0/12",
    );
  });

  it("documents the report in the Help tab", () => {
    expect(CompareAciSubnetsPlugin.HelpPanel).toBe(CompareAciSubnetsHelpPanel);
    render(<CompareAciSubnetsHelpPanel />);
    for (const word of ["missing_in_nautobot", "missing_in_aci", "overlaps", "scope_prefixes"]) {
      expect(screen.getAllByText(word).length).toBeGreaterThan(0);
    }
  });
});
