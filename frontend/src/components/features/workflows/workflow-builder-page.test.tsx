import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowBuilderPage } from "./workflow-builder-page";

// The page is an orchestrator: every hook and panel it wires has its own tests. These tests
// replace them with stubs and check the confirmation dialogs the page itself renders.
const h = await vi.hoisted(async () => {
  const { createElement } = await import("react");
  const persistence = {
    workflowId: 7 as number | null,
    workflowName: "Backup",
    isNewConfirmOpen: false,
    isOpenConfirmOpen: false,
    createWorkflow: { isPending: false },
    updateWorkflow: { isPending: false },
    setIsNewConfirmOpen: vi.fn(),
    setIsOpenConfirmOpen: vi.fn(),
    confirmNew: vi.fn(),
    handleDiscardAndOpen: vi.fn(),
    handleSaveAndOpen: vi.fn(),
    handleSave: vi.fn(),
    handleOpen: vi.fn(),
    handleLoadWorkflow: vi.fn(),
    setIsSaveAsOpen: vi.fn(),
  };
  const run = {
    isRunConfirmOpen: false,
    isRunInputsDialogOpen: false,
    runInputAttributes: [],
    isTriggeringRun: false,
    setIsRunConfirmOpen: vi.fn(),
    setIsRunInputsDialogOpen: vi.fn(),
    handleRun: vi.fn(),
    handleRunSavedVersion: vi.fn(),
    handleSaveAndRun: vi.fn(),
    handleRunInputsSubmit: vi.fn(),
    requestRun: vi.fn(),
  };
  // A marker element for a stubbed child; `createElement` keeps this usable inside the hoisted block.
  const stub = (name: string) => () => createElement("div", { "data-testid": name });
  return { persistence, run, stub };
});


vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/hooks/queries/use-workflow-steps-query", () => ({
  useWorkflowStepsQuery: () => ({ data: undefined, error: null, isLoading: false }),
}));
vi.mock("@/components/features/ai-assistant/hooks/use-ai-assistant-available", () => ({
  useAiAssistantAvailable: () => false,
}));
vi.mock("@/components/features/ai-assistant/hooks/use-assistant-session-open", () => ({
  useAssistantSessionOpen: () => ({ open: false, setOpen: vi.fn(), toggle: vi.fn() }),
}));
vi.mock("@/components/features/ai-assistant/components/assistant-panel", () => ({
  AssistantPanel: h.stub("assistant"),
}));
vi.mock("./hooks/use-unsaved-changes-warning", () => ({ useUnsavedChangesWarning: vi.fn() }));
vi.mock("./hooks/use-workflow-keyboard-shortcuts", () => ({
  useWorkflowKeyboardShortcuts: vi.fn(),
}));
vi.mock("./hooks/use-workflow-canvas", () => ({
  useWorkflowCanvas: () => ({
    allNodes: [],
    allEdges: [],
    groups: [],
    staticAttributes: [],
    projected: { nodes: [], edges: [] },
    activeGroupId: null,
    initialCanvasDraft: null,
  }),
}));
vi.mock("./hooks/use-workflow-persistence", () => ({
  useWorkflowPersistence: () => h.persistence,
}));
vi.mock("./hooks/use-workflow-run-actions", () => ({ useWorkflowRunActions: () => h.run }));
vi.mock("./hooks/use-workflow-validation", () => ({
  useWorkflowValidation: () => ({
    isValidating: false,
    isDialogOpen: false,
    result: null,
    validationByNodeId: {},
    handleValidate: vi.fn(),
    setIsDialogOpen: vi.fn(),
  }),
}));
vi.mock("./components/ai-session-update-banner", () => ({ AiSessionUpdateBanner: h.stub("banner") }));
vi.mock("./components/canvas-error-boundary", () => ({
  CanvasErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("./components/canvas-group-breadcrumb", () => ({ CanvasGroupBreadcrumb: h.stub("crumb") }));
vi.mock("./components/node-config-modal", () => ({ NodeConfigModal: h.stub("config") }));
vi.mock("./components/workflow-canvas", () => ({ WorkflowCanvas: h.stub("canvas") }));
vi.mock("./components/workflow-properties-panel", () => ({
  WorkflowPropertiesPanel: h.stub("properties"),
}));
vi.mock("./components/workflow-run-controls", () => ({ WorkflowRunControls: h.stub("controls") }));
vi.mock("./components/workflow-topbar", () => ({ WorkflowTopbar: h.stub("topbar") }));
vi.mock("./dialogs/step-library-dialog", () => ({ StepLibraryDialog: h.stub("library") }));
vi.mock("./dialogs/group-connection-dialog", () => ({ GroupConnectionDialog: h.stub("group-conn") }));
vi.mock("./dialogs/workflow-conflict-dialog", () => ({ WorkflowConflictDialog: h.stub("conflict") }));
vi.mock("./dialogs/workflow-history-dialog", () => ({ WorkflowHistoryDialog: h.stub("history") }));
vi.mock("./dialogs/workflow-manage-dialog", () => ({ WorkflowManageDialog: h.stub("manage") }));
vi.mock("./dialogs/workflow-open-dialog", () => ({ WorkflowOpenDialog: h.stub("open") }));
vi.mock("./dialogs/workflow-run-inputs-dialog", () => ({ WorkflowRunInputsDialog: h.stub("inputs") }));
vi.mock("./dialogs/workflow-save-as-dialog", () => ({ WorkflowSaveAsDialog: h.stub("save-as") }));
vi.mock("./dialogs/workflow-validation-dialog", () => ({
  WorkflowValidationDialog: h.stub("validation"),
}));
vi.mock("./dialogs/workflow-wiki-dialog", () => ({ WorkflowWikiDialog: h.stub("wiki") }));

const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

beforeEach(() => {
  vi.clearAllMocks();
  h.persistence.workflowId = 7;
  h.persistence.isNewConfirmOpen = false;
  h.persistence.isOpenConfirmOpen = false;
  h.persistence.createWorkflow.isPending = false;
  h.persistence.updateWorkflow.isPending = false;
  h.run.isRunConfirmOpen = false;
});

describe("WorkflowBuilderPage run confirmation", () => {
  it("shows no confirmation dialog by default", () => {
    render(<WorkflowBuilderPage />);
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
  });

  it("offers Cancel, Run saved version and Save & run for a saved workflow", () => {
    h.run.isRunConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    expect(
      screen.getByText("The current workflow has unsaved changes. Save before running?"),
    ).toBeTruthy();
    for (const name of ["Cancel", "Run saved version", "Save & run"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });

  it("offers no saved version to run for a workflow that was never saved", () => {
    h.run.isRunConfirmOpen = true;
    h.persistence.workflowId = null;
    render(<WorkflowBuilderPage />);
    expect(screen.getByText("This workflow has not been saved yet. Save before running?")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Run saved version" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save & run" })).toBeTruthy();
  });

  it("runs the saved version without saving", () => {
    h.run.isRunConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    click("Run saved version");
    expect(h.run.handleRunSavedVersion).toHaveBeenCalledTimes(1);
    expect(h.run.handleSaveAndRun).not.toHaveBeenCalled();
    expect(h.persistence.handleSave).not.toHaveBeenCalled();
  });

  it("saves and runs", () => {
    h.run.isRunConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    click("Save & run");
    expect(h.run.handleSaveAndRun).toHaveBeenCalledTimes(1);
    expect(h.run.handleRunSavedVersion).not.toHaveBeenCalled();
  });

  it("closes the dialog on Escape", () => {
    h.run.isRunConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(h.run.setIsRunConfirmOpen).toHaveBeenCalledWith(false);
  });

  it("closes the dialog on Cancel without running anything", () => {
    h.run.isRunConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    click("Cancel");
    expect(h.run.setIsRunConfirmOpen).toHaveBeenCalledWith(false);
    expect(h.run.handleRunSavedVersion).not.toHaveBeenCalled();
    expect(h.run.handleSaveAndRun).not.toHaveBeenCalled();
  });

  it.each([
    ["an update", "updateWorkflow"],
    ["a create", "createWorkflow"],
  ] as const)("disables Save & run while %s is pending", (_label, key) => {
    h.run.isRunConfirmOpen = true;
    h.persistence[key].isPending = true;
    render(<WorkflowBuilderPage />);
    const button = screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("still allows running the saved version while a save is pending", () => {
    h.run.isRunConfirmOpen = true;
    h.persistence.updateWorkflow.isPending = true;
    render(<WorkflowBuilderPage />);
    expect((screen.getByRole("button", { name: "Run saved version" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});

describe("WorkflowBuilderPage new and open confirmations", () => {
  it("asks before discarding the workflow for a new one", () => {
    h.persistence.isNewConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    expect(screen.getByText("Discard unsaved changes?")).toBeTruthy();
    click("Keep editing");
    expect(h.persistence.setIsNewConfirmOpen).toHaveBeenCalledWith(false);
    expect(h.persistence.confirmNew).not.toHaveBeenCalled();
    click("Discard & create new");
    expect(h.persistence.confirmNew).toHaveBeenCalledTimes(1);
  });

  it("offers to cancel, discard or save before opening another workflow", () => {
    h.persistence.isOpenConfirmOpen = true;
    render(<WorkflowBuilderPage />);
    click("Cancel");
    expect(h.persistence.setIsOpenConfirmOpen).toHaveBeenCalledWith(false);
    click("Discard & open");
    expect(h.persistence.handleDiscardAndOpen).toHaveBeenCalledTimes(1);
    click("Save & open");
    expect(h.persistence.handleSaveAndOpen).toHaveBeenCalledTimes(1);
  });

  it("disables Save & open while the save is pending", () => {
    h.persistence.isOpenConfirmOpen = true;
    h.persistence.updateWorkflow.isPending = true;
    render(<WorkflowBuilderPage />);
    expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
