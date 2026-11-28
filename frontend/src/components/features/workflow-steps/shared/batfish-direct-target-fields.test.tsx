import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BatfishDirectTargetFields } from "./batfish-direct-target-fields";

vi.mock("@/hooks/queries/use-batfish-networks-query", () => ({
  useBatfishNetworksQuery: () => ({ data: { networks: [] } }),
}));
vi.mock("@/hooks/queries/use-batfish-snapshots-query", () => ({
  useBatfishSnapshotsQuery: () => ({ data: { snapshots: [] } }),
}));
vi.mock("./batfish-source-select-dialog", () => ({
  BatfishSourceSelectDialog: () => null,
}));

const CLEAR_BUTTON = /Use this run's snapshot/;

function setup(config: Record<string, unknown>) {
  const onChange = vi.fn();
  render(<BatfishDirectTargetFields config={config} onChange={onChange} />);
  return onChange;
}

describe("BatfishDirectTargetFields", () => {
  it("offers no clear button and no warning when nothing is set", () => {
    setup({ output_key: "k" });
    expect(screen.queryByRole("button", { name: CLEAR_BUTTON })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("warns when a source is set without a network", () => {
    setup({ batfish_source_id: "batfish" });
    expect(screen.getByRole("alert").textContent).toContain("Set both Source and Network");
  });

  it("does not warn when source and network are both set", () => {
    setup({ batfish_source_id: "batfish", network: "manus-production" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears source, network and snapshot and keeps the other keys", () => {
    const onChange = setup({
      output_key: "k",
      batfish_source_id: "batfish",
      network: "n",
      snapshot: "s",
    });
    fireEvent.click(screen.getByRole("button", { name: CLEAR_BUTTON }));
    expect(onChange).toHaveBeenCalledWith({
      output_key: "k",
      batfish_source_id: "",
      network: "",
      snapshot: "",
    });
  });
});
