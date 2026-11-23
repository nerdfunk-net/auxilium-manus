import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { GetAgeOfBackupPlugin } from "./index";

vi.mock("@/components/features/workflow-steps/shared/git-repository-value", () => ({
  GitRepositoryValue: () => <div>repository</div>,
}));
vi.mock("@/components/features/workflow-steps/shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: () => null,
}));

const Panel = GetAgeOfBackupPlugin.ConfigPanel;

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

describe("GetAgeOfBackupConfigPanel", () => {
  it("shows the defaults for an empty config", () => {
    mount({});
    expect(screen.getByDisplayValue("{device.name}.cfg")).toBeTruthy();
    expect(screen.getByDisplayValue("backup_age")).toBeTruthy();
  });

  it("offers the stale-repository switch and stores it", () => {
    const { last } = mount({ git_repository_id: 3 });
    fireEvent.click(screen.getByLabelText("allow_stale_repository"));
    expect(last()).toMatchObject({ allow_stale_repository: true, git_repository_id: 3 });
  });

  it("keeps every other field when the path template is edited", () => {
    const { last } = mount({
      git_repository_id: 3,
      allow_stale_repository: true,
      output_bag: "cfg_age",
      use_marker: true,
      marker_storage_key: "checked",
    });
    fireEvent.change(screen.getByDisplayValue("{device.name}.cfg"), {
      target: { value: "{nautobot.location.name}/{device.name}.cfg" },
    });
    expect(last()).toEqual({
      git_repository_id: 3,
      allow_stale_repository: true,
      path_template: "{nautobot.location.name}/{device.name}.cfg",
      output_bag: "cfg_age",
      use_marker: true,
      marker_storage_key: "checked",
    });
  });

  it("stores a new bag name", () => {
    const { last } = mount({ git_repository_id: 3 });
    fireEvent.change(screen.getByDisplayValue("backup_age"), { target: { value: "cfg_age" } });
    expect(last()).toMatchObject({ output_bag: "cfg_age" });
  });

  it("hides the marker key until the marker is switched on", () => {
    const { last } = mount({ git_repository_id: 3 });
    expect(screen.queryByPlaceholderText("backup_checked")).toBeNull();

    fireEvent.click(screen.getByLabelText("use_marker"));
    expect(last()).toMatchObject({ use_marker: true });

    fireEvent.change(screen.getByPlaceholderText("backup_checked"), {
      target: { value: "backup_checked" },
    });
    expect(last()).toMatchObject({ use_marker: true, marker_storage_key: "backup_checked" });
  });

  it("warns while the marker is on but has no key", () => {
    mount({ git_repository_id: 3, use_marker: true, marker_storage_key: "" });
    expect(screen.getByText(/Enter the storage key/)).toBeTruthy();
  });
});
