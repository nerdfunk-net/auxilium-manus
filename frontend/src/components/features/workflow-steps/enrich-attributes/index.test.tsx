import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { EnrichAttributesPlugin } from "./index";

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/components/features/workflow-steps/shared/attribute-path-picker", () => ({
  AttributePathPicker: ({ open, onSelect }: { open: boolean; onSelect: (p: string) => void }) =>
    open ? <button onClick={() => onSelect("nautobot.serial")}>pick serial</button> : null,
}));

vi.mock("@/components/features/workflow-steps/shared/git-repository-value", () => ({
  GitRepositoryValue: () => <div>repository</div>,
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: () => null,
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

describe("EnrichAttributesConfigPanel git refresh switches", () => {
  it("offers refresh_repository, off by default, and hides the stale switch until it is on", () => {
    const { last } = mount({ source: "git", git_repository_id: 3 });

    expect(screen.getByText("refresh_repository")).toBeTruthy();
    expect(screen.queryByText("allow_stale_repository")).toBeNull();
    expect(last()?.refresh_repository ?? false).toBe(false);

    fireEvent.click(screen.getByLabelText("refresh_repository"));

    expect(last()).toMatchObject({ refresh_repository: true, git_repository_id: 3 });
    expect(screen.getByText("allow_stale_repository")).toBeTruthy();
  });

  it("clears allow_stale_repository when refresh is turned off, so it cannot come back unseen", () => {
    const { last } = mount({
      source: "git",
      git_repository_id: 3,
      refresh_repository: true,
      allow_stale_repository: true,
    });

    fireEvent.click(screen.getByLabelText("refresh_repository"));

    expect(last()).toMatchObject({ refresh_repository: false, allow_stale_repository: false });
    expect(screen.queryByText("allow_stale_repository")).toBeNull();

    fireEvent.click(screen.getByLabelText("refresh_repository"));
    expect(last()).toMatchObject({ refresh_repository: true, allow_stale_repository: false });
  });
});
