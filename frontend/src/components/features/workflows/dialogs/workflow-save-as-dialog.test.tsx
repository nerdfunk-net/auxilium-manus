import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowSaveAsDialog } from "./workflow-save-as-dialog";

const h = vi.hoisted(() => ({
  checkName: vi.fn(),
  hasRepo: { value: false },
}));
vi.mock("@/hooks/queries/use-workflow-check-name", () => ({
  useWorkflowCheckNameMutation: () => ({ mutateAsync: h.checkName }),
}));
vi.mock("../hooks/use-workflow-git-repositories", () => ({
  useWorkflowGitRepositories: () => ({ hasConfiguredGitRepository: h.hasRepo.value }),
}));

function setup(props: Partial<React.ComponentProps<typeof WorkflowSaveAsDialog>> = {}) {
  const handlers = { onSave: vi.fn(), onOverwrite: vi.fn(), onClose: vi.fn() };
  render(<WorkflowSaveAsDialog open defaultName="Backup" {...handlers} {...props} />);
  return handlers;
}

const submit = () => fireEvent.click(screen.getByRole("button", { name: "Save" }));
const typeInto = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

beforeEach(() => {
  h.checkName.mockReset();
  h.checkName.mockResolvedValue({ available: true });
  h.hasRepo.value = false;
});

describe("WorkflowSaveAsDialog", () => {
  it("renders nothing while closed", () => {
    render(<WorkflowSaveAsDialog open={false} onSave={vi.fn()} onOverwrite={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText("Save Workflow As")).toBeNull();
  });

  it("starts from the defaults", () => {
    setup({ defaultDescription: "nightly", defaultFolder: "/net" });
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Backup");
    expect((screen.getByLabelText("Description") as HTMLInputElement).value).toBe("nightly");
    expect((screen.getByLabelText("Folder") as HTMLInputElement).value).toBe("/net");
  });

  it("checks the name, then saves the entered values", async () => {
    const { onSave } = setup({ defaultVisibility: "public" });
    typeInto("Description", "d");
    submit();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(h.checkName).toHaveBeenCalledWith({ name: "Backup", folder: "/", visibility: "public" });
    expect(onSave).toHaveBeenCalledWith({
      name: "Backup",
      description: "d",
      folder: "/",
      visibility: "public",
      is_version_controlled: false,
    });
  });

  it("does not submit without a name", async () => {
    const { onSave } = setup({ defaultName: "" });
    submit();
    expect(await screen.findByText("Name is required")).toBeTruthy();
    expect(h.checkName).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("saves into the root folder when the folder was cleared", async () => {
    const { onSave } = setup();
    typeInto("Folder", "");
    submit();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(h.checkName).toHaveBeenCalledWith(expect.objectContaining({ folder: "/" }));
    expect(onSave.mock.calls[0]![0].folder).toBe("/");
  });

  it("overwrites into the root folder when the folder was cleared", async () => {
    h.checkName.mockResolvedValue({ available: false, message: "exists", existing_id: 12 });
    const { onOverwrite } = setup();
    typeInto("Folder", "");
    submit();
    fireEvent.click(await screen.findByRole("button", { name: "Overwrite" }));
    expect(onOverwrite).toHaveBeenCalledTimes(1);
    expect(onOverwrite.mock.calls[0]![0].folder).toBe("/");
  });

  it("offers to overwrite a workflow of the same name instead of saving", async () => {
    h.checkName.mockResolvedValue({
      available: false,
      message: 'You already have a private workflow named "Backup" in folder "/".',
      existing_id: 12,
    });
    const { onSave, onOverwrite } = setup();
    submit();
    expect(await screen.findByText(/You already have a private workflow/)).toBeTruthy();
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Overwrite" }));
    expect(onOverwrite).toHaveBeenCalledWith(expect.objectContaining({ name: "Backup" }), 12);
  });

  it("falls back to a generic message when the server sends none", async () => {
    h.checkName.mockResolvedValue({ available: false, existing_id: 3 });
    setup();
    submit();
    expect(await screen.findByText("A workflow with this name already exists.")).toBeTruthy();
  });

  it("hides the overwrite offer once the name or folder changes", async () => {
    h.checkName.mockResolvedValue({ available: false, message: "exists", existing_id: 12 });
    setup();
    submit();
    await screen.findByRole("button", { name: "Overwrite" });
    typeInto("Name", "Backup 2");
    expect(screen.queryByRole("button", { name: "Overwrite" })).toBeNull();

    submit();
    await screen.findByRole("button", { name: "Overwrite" });
    typeInto("Folder", "/other");
    expect(screen.queryByRole("button", { name: "Overwrite" })).toBeNull();
  });

  it("lets the user choose a different name", async () => {
    h.checkName.mockResolvedValue({ available: false, message: "exists", existing_id: 12 });
    setup();
    submit();
    fireEvent.click(await screen.findByRole("button", { name: "Choose different name" }));
    expect(screen.queryByText("exists")).toBeNull();
  });

  it("still saves when the name check itself fails", async () => {
    h.checkName.mockRejectedValue(new Error("403"));
    const { onSave } = setup();
    submit();
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });

  it("does nothing when the name is taken but the server named no workflow", async () => {
    h.checkName.mockResolvedValue({ available: false });
    const { onSave, onOverwrite } = setup();
    submit();
    await waitFor(() => expect(h.checkName).toHaveBeenCalled());
    expect(onSave).not.toHaveBeenCalled();
    expect(onOverwrite).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Overwrite" })).toBeNull();
  });

  it("shows the saving state and disables the button", () => {
    setup({ isSaving: true });
    const button = screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("disables the Save button while the name is being checked", async () => {
    let resolve: (v: unknown) => void = () => {};
    h.checkName.mockReturnValue(new Promise((r) => (resolve = r)));
    const { onSave } = setup();
    submit();
    const button = (await screen.findByRole("button", { name: "Checking…" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    resolve({ available: true });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it("cannot turn on version control without a configured Git repository", () => {
    setup();
    const toggle = screen.getByRole("switch", { name: "Version controlled" }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(screen.getByText(/Configure a Git repository in Settings/)).toBeTruthy();
  });

  it("lets the user turn on version control when a repository exists", async () => {
    h.hasRepo.value = true;
    const { onSave } = setup();
    const toggle = screen.getByRole("switch", { name: "Version controlled" });
    expect((toggle as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(toggle);
    submit();
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0]![0].is_version_controlled).toBe(true);
  });

  it("keeps an already version controlled workflow switchable without a repository", () => {
    setup({ defaultIsVersionControlled: true });
    const toggle = screen.getByRole("switch", { name: "Version controlled" }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(false);
  });

  it("closes through Cancel", () => {
    const { onClose } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
