import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ReadFromFilePlugin } from "./index";

vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
vi.mock("@/components/features/workflow-steps/shared/git-repository-value", () => ({
  GitRepositoryValue: () => <div>repository</div>,
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: () => null,
}));

const Panel = ReadFromFilePlugin.ConfigPanel;

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

describe("ReadFromFileConfigPanel allow_stale_repository", () => {
  it("shows no stale switch for the filesystem source", () => {
    mount({ source: "filesystem" });
    expect(screen.queryByText("allow_stale_repository")).toBeNull();
  });

  it("offers the switch for a git source and stores it", () => {
    const { last } = mount({ source: "git", git_repository_id: 3, path: "a.yaml" });
    fireEvent.click(screen.getByLabelText("allow_stale_repository"));
    expect(last()).toMatchObject({ allow_stale_repository: true, git_repository_id: 3 });
  });

  it("keeps the flag when another field is edited afterwards", () => {
    const { last } = mount({ source: "git", git_repository_id: 3, allow_stale_repository: true });
    fireEvent.change(screen.getByPlaceholderText("data/site-defaults.yaml"), {
      target: { value: "b.yaml" },
    });
    expect(last()).toMatchObject({ path: "b.yaml", allow_stale_repository: true });
  });
});
