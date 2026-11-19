import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ReadConfigPlugin } from "./index";

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/components/features/workflow-steps/shared/git-repository-value", () => ({
  GitRepositoryValue: () => <div>repository</div>,
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: () => null,
}));

const Panel = ReadConfigPlugin.ConfigPanel;

function mount(initial: Record<string, unknown>) {
  const changes: Record<string, unknown>[] = [];
  function Harness() {
    const [config, setConfig] = useState(initial);
    return (
      <Panel
        nodeId="n1"
        config={config}
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

describe("ReadConfigConfigPanel allow_stale_repository", () => {
  it("shows no stale switch for the filesystem source", () => {
    mount({ source: "filesystem" });
    expect(screen.queryByText("allow_stale_repository")).toBeNull();
  });

  it("offers the switch for a git source and stores it", () => {
    const { last } = mount({ source: "git", git_repository_id: 3 });
    fireEvent.click(screen.getByLabelText("allow_stale_repository"));
    expect(last()).toMatchObject({ allow_stale_repository: true, git_repository_id: 3 });
  });

  it("keeps the flag when another field is edited afterwards", () => {
    const { last } = mount({ source: "git", git_repository_id: 3, allow_stale_repository: true });
    fireEvent.change(screen.getByDisplayValue("{device.name}.cfg"), {
      target: { value: "{device.hostname}.cfg" },
    });
    expect(last()).toMatchObject({
      path_template: "{device.hostname}.cfg",
      allow_stale_repository: true,
    });
  });
});
