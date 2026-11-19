import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { EnrichAttributesPlugin } from "./index";

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/components/features/workflow-steps/shared/attribute-path-picker", () => ({
  AttributePathPicker: ({ open, onSelect }: { open: boolean; onSelect: (p: string) => void }) =>
    open ? <button onClick={() => onSelect("nautobot.serial")}>pick serial</button> : null,
}));

const Panel = EnrichAttributesPlugin.ConfigPanel;

function mount(initial: Record<string, unknown> = {}) {
  const changes: Record<string, unknown>[] = [];
  function Harness() {
    const [config, setConfig] = useState(initial);
    return (
      <Panel
        nodeId="self"
        config={config}
        workflowNodes={[]}
        workflowEdges={[]}
        onPreview={() => undefined}
        onChange={(next) => {
          changes.push(next);
          setConfig(next);
        }}
      />
    );
  }
  render(<Harness />);
  return { last: () => changes[changes.length - 1] };
}

describe("EnrichAttributesConfigPanel device_attribute_path picker", () => {
  it("fills device_attribute_path from the picker and keeps the other fields", () => {
    const { last } = mount({ key_column: "serial", path: "a.csv" });
    expect(screen.queryByText("pick serial")).toBeNull();

    fireEvent.click(screen.getByTitle("Browse attributes"));
    fireEvent.click(screen.getByText("pick serial"));

    expect(last()).toMatchObject({
      device_attribute_path: "nautobot.serial",
      key_column: "serial",
      path: "a.csv",
    });
    expect(screen.getByPlaceholderText("nautobot.serial")).toHaveProperty(
      "value",
      "nautobot.serial",
    );
  });

  it("still allows typing the path by hand", () => {
    const { last } = mount();
    fireEvent.change(screen.getByPlaceholderText("nautobot.serial"), {
      target: { value: "nautobot.name" },
    });
    expect(last()).toMatchObject({ device_attribute_path: "nautobot.name" });
  });
});
