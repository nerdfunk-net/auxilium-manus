import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { BatfishBgpFactsPlugin } from "./batfish-bgp-facts";
import { BatfishOspfFactsPlugin } from "./batfish-ospf-facts";

vi.mock("./shared/batfish-direct-target-fields", () => ({
  BatfishDirectTargetFields: () => null,
}));

function renderPanel(plugin: typeof BatfishBgpFactsPlugin) {
  const Panel = plugin.ConfigPanel;
  const props = { config: {}, onChange: vi.fn() } as unknown as PluginConfigPanelProps;
  render(<Panel {...props} />);
}

describe("combined Batfish fact panels", () => {
  it("BGP Facts offers its four questions and its default output key", () => {
    renderPanel(BatfishBgpFactsPlugin);
    for (const label of ["Process", "Peers", "Sessions", "Adjacencies"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByPlaceholderText("batfish_bgp_facts")).toBeTruthy();
  });

  it("OSPF Facts offers its four questions and its default output key", () => {
    renderPanel(BatfishOspfFactsPlugin);
    for (const label of ["Process", "Areas", "Interfaces", "Adjacencies"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByPlaceholderText("batfish_ospf_facts")).toBeTruthy();
  });
});
