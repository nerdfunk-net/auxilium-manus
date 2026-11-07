import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BackupAciConfigHelpPanel } from "./help-panel";
import { BackupAciConfigPlugin } from "./index";

vi.mock("../shared/aci-source-select-dialog", () => ({
  AciSourceSelectDialog: ({ open, onSave }: { open: boolean; onSave: (id: string) => void }) =>
    open ? <button onClick={() => onSave("lab")}>pick aci</button> : null,
}));
vi.mock("../shared/git-repository-select-dialog", () => ({
  GitRepositorySelectDialog: ({
    open,
    onSave,
  }: {
    open: boolean;
    onSave: (id: number) => void;
  }) => (open ? <button onClick={() => onSave(7)}>pick repository</button> : null),
}));
vi.mock("../shared/git-repository-value", () => ({
  GitRepositoryValue: ({ repositoryId }: { repositoryId: number | null }) => (
    <p>{repositoryId === null ? "no repository" : `repository ${repositoryId}`}</p>
  ),
}));

const { ConfigPanel } = BackupAciConfigPlugin;

type Config = Record<string, unknown>;

function setup(config: Config) {
  const onChange = vi.fn<(next: Config) => void>();
  render(<ConfigPanel nodeId="n1" config={config} onChange={onChange} onPreview={vi.fn()} />);
  return onChange;
}

function last(onChange: ReturnType<typeof setup>): Config {
  return onChange.mock.calls.at(-1)![0];
}

function toggle(label: string): HTMLElement {
  return screen.getByLabelText(label);
}

describe("backup-aci-config config panel", () => {
  it("shows the defaults", () => {
    setup({});
    expect(screen.getByText("Not configured")).toBeTruthy();
    expect(screen.getByText("no repository")).toBeTruthy();
    expect(screen.getByDisplayValue("aci")).toBeTruthy();
    expect(screen.getByDisplayValue("aci_backup")).toBeTruthy();
    expect(toggle("include_access_policies").getAttribute("aria-checked")).toBe("true");
    expect(toggle("commit").getAttribute("aria-checked")).toBe("true");
    expect(toggle("push").getAttribute("aria-checked")).toBe("false");
  });

  it("stores the chosen source and repository", () => {
    const onChange = setup({});
    fireEvent.click(screen.getByText("Configure Source"));
    fireEvent.click(screen.getByText("pick aci"));
    expect(last(onChange)).toEqual({ aci_source_id: "lab" });
    fireEvent.click(screen.getByText("Choose repository"));
    fireEvent.click(screen.getByText("pick repository"));
    expect(last(onChange)).toEqual({ git_repository_id: 7 });
  });

  it("writes the folder, tenants, message and output key", () => {
    const onChange = setup({ aci_source_id: "lab" });
    fireEvent.change(screen.getByDisplayValue("aci"), { target: { value: "fabric1" } });
    expect(last(onChange)).toMatchObject({ repository_subdirectory: "fabric1", aci_source_id: "lab" });
    fireEvent.change(screen.getByPlaceholderText("All tenants"), {
      target: { value: "Heroes\nSnV" },
    });
    expect(last(onChange).tenants).toEqual(["Heroes", "SnV"]);
    fireEvent.change(screen.getByDisplayValue("ACI configuration backup of {source_id}"), {
      target: { value: "backup" },
    });
    expect(last(onChange).commit_message).toBe("backup");
    fireEvent.change(screen.getByDisplayValue("aci_backup"), { target: { value: "bk" } });
    expect(last(onChange).output_key).toBe("bk");
  });

  it("turns the push off with the commit and disables it", () => {
    const onChange = setup({ commit: true, push: true });
    fireEvent.click(toggle("commit"));
    expect(last(onChange)).toMatchObject({ commit: false, push: false });
  });

  it("disables the push while the commit is off", () => {
    setup({ commit: false });
    expect((toggle("push") as HTMLButtonElement).disabled).toBe(true);
  });

  it("writes the access policies switch", () => {
    const onChange = setup({});
    fireEvent.click(toggle("include_access_policies"));
    expect(last(onChange).include_access_policies).toBe(false);
  });

  it("documents the files and the all-or-nothing rule in the Help tab", () => {
    expect(BackupAciConfigPlugin.HelpPanel).toBe(BackupAciConfigHelpPanel);
    render(<BackupAciConfigHelpPanel />);
    expect(screen.getAllByText("stale_files").length).toBeGreaterThan(0);
    expect(screen.getAllByText("push").length).toBeGreaterThan(0);
    expect(screen.getByText(/writes nothing/)).toBeTruthy();
  });
});
