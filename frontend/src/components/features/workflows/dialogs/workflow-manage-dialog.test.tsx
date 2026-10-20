import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import type { WorkflowSummary } from "../types/workflow-persistence";
import { WorkflowManageDialog } from "./workflow-manage-dialog";

const h = vi.hoisted(() => ({
  query: { data: undefined as unknown, isLoading: false, error: null as Error | null },
  hasRepo: { value: true },
  updateMutate: vi.fn(),
  deleteMutate: vi.fn(),
  exportMutate: vi.fn(),
  toast: vi.fn(),
  update: { isPending: false },
  del: { isPending: false },
}));

vi.mock("@/hooks/queries/use-workflows-query", () => ({ useWorkflowsQuery: () => h.query }));
vi.mock("@/hooks/queries/use-workflow-mutations", () => ({
  useWorkflowMutations: () => ({
    updateWorkflow: { mutate: h.updateMutate, isPending: h.update.isPending },
    deleteWorkflow: { mutate: h.deleteMutate, isPending: h.del.isPending },
  }),
}));
vi.mock("@/hooks/queries/use-workflow-export-mutation", () => ({
  useWorkflowExportMutation: () => ({ mutate: h.exportMutate, isPending: false, variables: undefined }),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));
vi.mock("../hooks/use-workflow-git-repositories", () => ({
  useWorkflowGitRepositories: () => ({ hasConfiguredGitRepository: h.hasRepo.value }),
}));
vi.mock("./workflow-import-dialog", () => ({
  WorkflowImportDialog: ({ open }: { open: boolean }) => (open ? <div>import dialog</div> : null),
}));
vi.mock("./workflow-gallery-dialog", () => ({
  WorkflowGalleryDialog: ({ open }: { open: boolean }) => (open ? <div>gallery dialog</div> : null),
}));

const wf = (id: number, name: string, over: Partial<WorkflowSummary> = {}): WorkflowSummary =>
  ({
    id,
    name,
    description: null,
    folder: "/",
    visibility: "private",
    is_version_controlled: false,
    creator_username: "alice",
    updated_at: "2026-10-19T10:00:00Z",
    ...over,
  }) as WorkflowSummary;

const WORKFLOWS = [wf(1, "Backup"), wf(2, "Audit", { folder: "/net" }), wf(3, "Patch", { folder: "/net" })];

function setup(workflows: WorkflowSummary[] = WORKFLOWS) {
  h.query.data = { workflows, total: workflows.length };
  const { wrapper: Wrapper, client } = createQueryWrapper();
  client.setQueryData(queryKeys.workflows.list(), { workflows, total: workflows.length });
  const onClose = vi.fn();
  render(
    <Wrapper>
      <WorkflowManageDialog open onClose={onClose} />
    </Wrapper>,
  );
  return { onClose, client };
}

// The name also appears in the "Editing: <name>" line, so pick the row's own label.
const rowOf = (name: string) =>
  screen
    .getAllByText(name)
    .find((el) => el.className.includes("text-sm"))!
    .closest("div.rounded-lg") as HTMLElement;
// A folder name also shows as a badge on each row; the sidebar entry is the one inside a <button>.
const folderButton = (label: string) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest("button"))
    .find((el): el is HTMLButtonElement => el !== null)!;
const clickIn = (name: string, label: string) =>
  fireEvent.click(within(rowOf(name)).getByRole("button", { name: label }));

beforeEach(() => {
  h.query.data = undefined;
  h.query.isLoading = false;
  h.query.error = null;
  h.hasRepo.value = true;
  h.update.isPending = false;
  h.del.isPending = false;
  for (const fn of [h.updateMutate, h.deleteMutate, h.exportMutate, h.toast]) fn.mockReset();
});

describe("WorkflowManageDialog list", () => {
  it("lists every workflow and filters by folder", () => {
    setup();
    for (const name of ["Backup", "Audit", "Patch"]) expect(screen.getByText(name)).toBeTruthy();
    fireEvent.click(folderButton("net"));
    expect(screen.queryByText("Backup")).toBeNull();
    expect(screen.getByText("Audit")).toBeTruthy();
    fireEvent.click(folderButton("All"));
    expect(screen.getByText("Backup")).toBeTruthy();
  });

  it("files a workflow with an empty folder under Root", () => {
    setup([wf(1, "Odd", { folder: "" as unknown as string })]);
    fireEvent.click(folderButton("Root"));
    expect(screen.getByText("Odd")).toBeTruthy();
  });

  it("says when nothing is stored, while loading, and on a load error", () => {
    setup([]);
    expect(screen.getByText("No workflows in this folder.")).toBeTruthy();
  });

  it("shows the loading state", () => {
    h.query.isLoading = true;
    setup([]);
    expect(screen.getByText("Loading…")).toBeTruthy();
  });

  it("shows the load error", () => {
    h.query.error = new Error("x");
    setup([]);
    expect(screen.getByText("Failed to load workflows.")).toBeTruthy();
  });

  it("exports the chosen workflow", () => {
    setup();
    clickIn("Audit", "Export workflow");
    expect(h.exportMutate).toHaveBeenCalledWith(2);
  });

  it("opens the gallery and the import dialog and closes through Close", () => {
    const { onClose } = setup();
    fireEvent.click(screen.getByRole("button", { name: /Gallery/ }));
    expect(screen.getByText("gallery dialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Import/ }));
    expect(screen.getByText("import dialog")).toBeTruthy();
    // The dialog's own corner "x" is also named Close; the footer button is the text one.
    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    fireEvent.click(closeButtons[closeButtons.length - 1]!);
    expect(onClose).toHaveBeenCalled();
  });
});

describe("WorkflowManageDialog edit", () => {
  const openEdit = (name: string) => clickIn(name, "Edit workflow");
  const typeInto = (label: string, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });

  it("asks for a selection until a workflow is chosen", () => {
    setup();
    expect(screen.getByText("Select a workflow to edit its details.")).toBeTruthy();
  });

  it("fills the form with the chosen workflow", () => {
    setup([wf(2, "Audit", { folder: "/net", description: "weekly" })]);
    openEdit("Audit");
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Audit");
    expect((screen.getByLabelText("Folder") as HTMLInputElement).value).toBe("/net");
    expect((screen.getByLabelText("Description") as HTMLInputElement).value).toBe("weekly");
  });

  it("shows the root folder for a workflow stored without one", () => {
    setup([wf(1, "Odd", { folder: null as unknown as string })]);
    openEdit("Odd");
    expect((screen.getByLabelText("Folder") as HTMLInputElement).value).toBe("/");
  });

  it("drops a pending delete confirmation when another workflow is edited", () => {
    setup();
    clickIn("Audit", "Delete workflow");
    expect(screen.getByText(/This cannot be undone/)).toBeTruthy();
    clickIn("Backup", "Edit workflow");
    expect(screen.queryByText(/This cannot be undone/)).toBeNull();
  });

  it("saves the changes and patches the cached list", async () => {
    h.updateMutate.mockImplementation((_vars, handlers) =>
      handlers.onSuccess({
        id: 2,
        name: "Audit v2",
        description: "weekly",
        folder: "/net",
        visibility: "private",
        is_version_controlled: false,
        updated_at: "2026-10-20T10:00:00Z",
      }),
    );
    const { client } = setup();
    openEdit("Audit");
    typeInto("Name", "Audit v2");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(h.updateMutate).toHaveBeenCalledTimes(1));
    const [vars] = h.updateMutate.mock.calls[0]!;
    expect(vars.id).toBe(2);
    expect(vars.data).toEqual(
      expect.objectContaining({ name: "Audit v2", folder: "/net", visibility: "private" }),
    );
    const cached = client.getQueryData<{ workflows: WorkflowSummary[] }>(queryKeys.workflows.list());
    expect(cached?.workflows.find((w) => w.id === 2)?.name).toBe("Audit v2");
    expect(cached?.workflows.find((w) => w.id === 1)?.name).toBe("Backup");
    expect(await screen.findByText('"Audit v2" saved.')).toBeTruthy();
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("stores a cleared folder as the root folder", async () => {
    setup();
    openEdit("Audit");
    typeInto("Folder", "");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(h.updateMutate).toHaveBeenCalled());
    expect(h.updateMutate.mock.calls[0]![0].data.folder).toBe("/");
  });

  it("does not submit an empty name", async () => {
    setup();
    openEdit("Audit");
    typeInto("Name", "");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Name is required")).toBeTruthy();
    expect(h.updateMutate).not.toHaveBeenCalled();
  });

  it("shows the reason the server gave when the update fails", async () => {
    h.updateMutate.mockImplementation((_v, handlers) =>
      handlers.onError(new Error('A public workflow named "Audit" already exists.')),
    );
    setup();
    openEdit("Audit");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText('A public workflow named "Audit" already exists.')).toBeTruthy();
    expect(screen.getByLabelText("Name")).toBeTruthy();
  });

  it("falls back to a generic message when the failure carries none", async () => {
    h.updateMutate.mockImplementation((_v, handlers) => handlers.onError(new Error("")));
    setup();
    openEdit("Audit");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Failed to update workflow.")).toBeTruthy();
  });

  it("disables saving while the update is pending", () => {
    h.update.isPending = true;
    setup();
    openEdit("Audit");
    expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("cancels the edit without saving", () => {
    setup();
    openEdit("Audit");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(h.updateMutate).not.toHaveBeenCalled();
  });

  it("cannot switch version control on without a configured repository", () => {
    h.hasRepo.value = false;
    setup();
    openEdit("Audit");
    expect((screen.getByRole("switch") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Configure a Git repository in Settings/)).toBeTruthy();
  });

  it("lets a versioned workflow be switched off even without a repository", () => {
    h.hasRepo.value = false;
    setup([wf(1, "Backup", { is_version_controlled: true })]);
    openEdit("Backup");
    expect((screen.getByRole("switch") as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("WorkflowManageDialog delete", () => {
  it("asks for confirmation and can be cancelled", () => {
    setup();
    clickIn("Audit", "Delete workflow");
    expect(screen.getByText(/This cannot be undone/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/This cannot be undone/)).toBeNull();
    expect(h.deleteMutate).not.toHaveBeenCalled();
  });

  it("deletes the confirmed workflow and closes the confirmation", () => {
    h.deleteMutate.mockImplementation((_id, handlers) => handlers.onSuccess());
    setup();
    clickIn("Audit", "Delete workflow");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(h.deleteMutate.mock.calls[0]![0]).toBe(2);
    expect(screen.queryByText(/This cannot be undone/)).toBeNull();
  });

  it("closes the edit form of the workflow that is being deleted", () => {
    setup();
    clickIn("Audit", "Edit workflow");
    expect(screen.getByLabelText("Name")).toBeTruthy();
    clickIn("Audit", "Delete workflow");
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("keeps the edit form of another workflow open", () => {
    setup();
    clickIn("Audit", "Edit workflow");
    clickIn("Backup", "Delete workflow");
    expect(screen.getByLabelText("Name")).toBeTruthy();
  });

  it("tells the user why a delete failed", () => {
    h.deleteMutate.mockImplementation((_id, handlers) =>
      handlers.onError(new Error("The workflow has runs in progress; cancel or wait for them first")),
    );
    setup();
    clickIn("Audit", "Delete workflow");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Delete failed",
        description: "The workflow has runs in progress; cancel or wait for them first",
        variant: "destructive",
      }),
    );
    expect(screen.queryByText(/This cannot be undone/)).toBeNull();
    expect(screen.getByText("Audit")).toBeTruthy();
  });

  it("shows the deleting state", () => {
    h.del.isPending = true;
    setup();
    clickIn("Audit", "Delete workflow");
    expect((screen.getByRole("button", { name: "Deleting…" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
