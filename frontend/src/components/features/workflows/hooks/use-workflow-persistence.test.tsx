import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { PluginDefinition } from "../types/plugin-registry";
import type { WorkflowResponse } from "../types/workflow-persistence";
import type { UseWorkflowCanvasResult } from "./use-workflow-canvas";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";
import { useWorkflowPersistence } from "./use-workflow-persistence";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const loadedCanvas = vi.hoisted(() => ({
  value: { nodes: [], edges: [], groups: [], staticAttributes: [], migrated: false } as {
    nodes: never[];
    edges: never[];
    groups: never[];
    staticAttributes: never[];
    migrated: boolean;
  },
}));
vi.mock("../utils/apply-loaded-workflow", () => ({
  canvasFromWorkflowResponse: vi.fn(() => loadedCanvas.value),
}));

const save = vi.hoisted(() => ({
  handleSave: vi.fn(),
  handleSaveAs: vi.fn(),
  handleOverwrite: vi.fn(),
  handleSaveAndOpen: vi.fn(async () => undefined),
  createWorkflow: { data: undefined as { updated_at: string } | undefined },
  updateWorkflow: { data: undefined as { updated_at: string } | undefined },
  lastArgs: undefined as undefined | { baselineUpdatedAtRef: { current: string | null }; onSaveConflict: () => void },
}));
vi.mock("./use-workflow-save", () => ({
  useWorkflowSave: (args: NonNullable<typeof save.lastArgs>) => {
    save.lastArgs = args;
    return save;
  },
}));

const applyLoadedCanvas = vi.fn();
const clearCanvas = vi.fn();
const NO_NODES: never[] = [];
const NO_PLUGINS: PluginDefinition[] = [];

function workflow(overrides: Partial<WorkflowResponse> = {}): WorkflowResponse {
  return {
    id: 7,
    uuid: "uuid-7",
    name: "Backup",
    description: null,
    folder: null,
    visibility: "private",
    is_version_controlled: false,
    notes: null,
    updated_at: "2026-01-01T00:00:00Z",
    canvas_nodes: [],
    canvas_edges: [],
    canvas_groups: [],
    static_attributes: [],
    ...overrides,
  } as unknown as WorkflowResponse;
}

interface Props {
  mountWorkflowId: number | null;
  initialCanvasDraft: unknown;
  isPluginsLoading: boolean;
  plugins: PluginDefinition[];
}

function setup(initial: Partial<Props> = {}) {
  const { wrapper, client } = createQueryWrapper();
  const requestRunRef = { current: vi.fn() };
  const hook = renderHook(
    (props: Props) => {
      const canvas = {
        allNodes: NO_NODES,
        allEdges: NO_NODES,
        groups: NO_NODES,
        staticAttributes: NO_NODES,
        applyLoadedCanvas,
        clearCanvas,
        mountWorkflowId: props.mountWorkflowId,
        initialCanvasDraft: props.initialCanvasDraft,
      } as unknown as UseWorkflowCanvasResult;
      return useWorkflowPersistence({
        canvas,
        plugins: props.plugins,
        isPluginsLoading: props.isPluginsLoading,
        requestRunRef,
      });
    },
    {
      wrapper,
      initialProps: {
        mountWorkflowId: null,
        initialCanvasDraft: null,
        isPluginsLoading: false,
        plugins: NO_PLUGINS,
        ...initial,
      },
    },
  );
  return { ...hook, client };
}

const store = () => useWorkflowBuilderStore.getState();

beforeEach(() => {
  apiCall.mockReset();
  applyLoadedCanvas.mockReset();
  clearCanvas.mockReset();
  for (const spy of [save.handleSave, save.handleSaveAs, save.handleOverwrite, save.handleSaveAndOpen]) {
    spy.mockClear();
  }
  save.createWorkflow = { data: undefined };
  save.updateWorkflow = { data: undefined };
  loadedCanvas.value = { nodes: [], edges: [], groups: [], staticAttributes: [], migrated: false };
  store().resetToNew();
  store().markSaved();
});

describe("restoring the canvas on mount", () => {
  it("fetches the workflow and applies it", async () => {
    apiCall.mockResolvedValue(workflow());
    setup({ mountWorkflowId: 7 });

    await waitFor(() => expect(applyLoadedCanvas).toHaveBeenCalledWith(loadedCanvas.value));
    expect(apiCall).toHaveBeenCalledWith("workflows/7");
    expect(store().isDirty).toBe(false);
  });

  it("marks the workflow dirty when loading migrated it", async () => {
    loadedCanvas.value = { ...loadedCanvas.value, migrated: true };
    apiCall.mockResolvedValue(workflow());
    setup({ mountWorkflowId: 7 });

    await waitFor(() => expect(store().isDirty).toBe(true));
  });

  it.each([
    ["no workflow to restore", { mountWorkflowId: null }],
    ["a local draft is being resumed", { mountWorkflowId: 7, initialCanvasDraft: {} }],
    ["the plugins are still loading", { mountWorkflowId: 7, isPluginsLoading: true }],
  ])("does not fetch when %s", async (_name, props) => {
    setup(props);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("waits for the plugins before fetching", async () => {
    apiCall.mockResolvedValue(workflow());
    const { rerender } = setup({ mountWorkflowId: 7, isPluginsLoading: true });
    expect(apiCall).not.toHaveBeenCalled();

    rerender({
      mountWorkflowId: 7,
      initialCanvasDraft: null,
      isPluginsLoading: false,
      plugins: NO_PLUGINS,
    });
    await waitFor(() => expect(apiCall).toHaveBeenCalledWith("workflows/7"));
  });

  it("reports a failed fetch in the builder status", async () => {
    apiCall.mockRejectedValue(new Error("500"));
    setup({ mountWorkflowId: 7 });

    await waitFor(() => expect(store().workflowStatus).toBe("Error"));
    expect(store().lastAction).toBe("Failed to restore workflow canvas");
    expect(applyLoadedCanvas).not.toHaveBeenCalled();
  });

  // Unsaved edits made after the restore must survive a change of the plugin list.
  it("applies the fetched canvas only once, even if the plugin list changes afterwards", async () => {
    apiCall.mockResolvedValue(workflow());
    const { rerender } = setup({ mountWorkflowId: 7 });
    await waitFor(() => expect(applyLoadedCanvas).toHaveBeenCalledTimes(1));

    rerender({
      mountWorkflowId: 7,
      initialCanvasDraft: null,
      isPluginsLoading: false,
      plugins: [{ id: "new-step" } as PluginDefinition],
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(applyLoadedCanvas).toHaveBeenCalledTimes(1);
  });
});

describe("baselineUpdatedAt", () => {
  it("is null before anything has been synced", () => {
    const { result } = setup();
    expect(result.current.baselineUpdatedAt).toBeNull();
  });

  it("is the newest timestamp of the restore, create, update and load paths", async () => {
    apiCall.mockResolvedValue(workflow({ updated_at: "2026-03-01T00:00:00Z" }));
    const { result, rerender } = setup({ mountWorkflowId: 7 });
    await waitFor(() => expect(result.current.baselineUpdatedAt).toBe("2026-03-01T00:00:00Z"));

    save.createWorkflow = { data: { updated_at: "2026-02-01T00:00:00Z" } };
    rerender({ mountWorkflowId: 7, initialCanvasDraft: null, isPluginsLoading: false, plugins: NO_PLUGINS });
    expect(result.current.baselineUpdatedAt).toBe("2026-03-01T00:00:00Z");

    save.updateWorkflow = { data: { updated_at: "2026-04-01T00:00:00Z" } };
    rerender({ mountWorkflowId: 7, initialCanvasDraft: null, isPluginsLoading: false, plugins: NO_PLUGINS });
    expect(result.current.baselineUpdatedAt).toBe("2026-04-01T00:00:00Z");
  });

  it("is handed to the save hook through its ref", async () => {
    apiCall.mockResolvedValue(workflow({ updated_at: "2026-03-01T00:00:00Z" }));
    setup({ mountWorkflowId: 7 });
    await waitFor(() =>
      expect(save.lastArgs?.baselineUpdatedAtRef.current).toBe("2026-03-01T00:00:00Z"),
    );
  });
});

describe("handleLoadWorkflow", () => {
  it("loads the canvas and metadata, applying defaults for missing fields", async () => {
    apiCall.mockResolvedValue(workflow());
    const { result } = setup();

    await act(async () => result.current.handleLoadWorkflow({ id: 7 }));

    await waitFor(() => expect(applyLoadedCanvas).toHaveBeenCalled());
    expect(apiCall).toHaveBeenCalledWith("workflows/7");
    expect(store()).toMatchObject({
      workflowId: 7,
      workflowUuid: "uuid-7",
      workflowName: "Backup",
      workflowDescription: "",
      workflowFolder: "/",
      workflowVisibility: "private",
      workflowNotes: null,
      isDirty: false,
    });
  });

  it("advances the baseline so the AI-updates banner clears after a reload", async () => {
    apiCall.mockResolvedValue(workflow({ updated_at: "2026-05-01T00:00:00Z" }));
    const { result } = setup();

    await act(async () => result.current.handleLoadWorkflow({ id: 7 }));

    await waitFor(() => expect(result.current.baselineUpdatedAt).toBe("2026-05-01T00:00:00Z"));
  });

  it("keeps the workflow dirty when loading migrated it", async () => {
    loadedCanvas.value = { ...loadedCanvas.value, migrated: true };
    apiCall.mockResolvedValue(workflow());
    const { result } = setup();

    await act(async () => result.current.handleLoadWorkflow({ id: 7 }));

    await waitFor(() => expect(store().isDirty).toBe(true));
  });

  it("reports a failed load and leaves the canvas alone", async () => {
    apiCall.mockRejectedValue(new Error("nope"));
    const { result } = setup();

    await act(async () => result.current.handleLoadWorkflow({ id: 7 }));

    await waitFor(() => expect(store().lastAction).toBe("Failed to load workflow"));
    expect(applyLoadedCanvas).not.toHaveBeenCalled();
  });
});

describe("handleRestored", () => {
  it("applies the restored version, marks it saved and advances the baseline", () => {
    const { result } = setup();
    store().markDirty();

    act(() => result.current.handleRestored(workflow({ name: "Old", updated_at: "2026-06-01T00:00:00Z" })));

    expect(applyLoadedCanvas).toHaveBeenCalledWith(loadedCanvas.value);
    expect(store()).toMatchObject({ workflowName: "Old", isDirty: false, lastAction: 'Restored "Old"' });
    expect(result.current.baselineUpdatedAt).toBe("2026-06-01T00:00:00Z");
  });
});

describe("new / open with unsaved changes", () => {
  it("handleNew resets immediately when nothing is unsaved", () => {
    const { result } = setup();
    act(() => result.current.handleNew());
    expect(clearCanvas).toHaveBeenCalledTimes(1);
    expect(result.current.isNewConfirmOpen).toBe(false);
  });

  it("handleNew asks first when there are unsaved changes, and only then clears", () => {
    const { result } = setup();
    act(() => store().markDirty());

    act(() => result.current.handleNew());
    expect(result.current.isNewConfirmOpen).toBe(true);
    expect(clearCanvas).not.toHaveBeenCalled();

    act(() => result.current.confirmNew());
    expect(clearCanvas).toHaveBeenCalledTimes(1);
    expect(result.current.isNewConfirmOpen).toBe(false);
    expect(store().workflowId).toBeNull();
  });

  it("handleOpen opens the dialog directly when clean and asks first when dirty", () => {
    const { result } = setup();
    act(() => result.current.handleOpen());
    expect(result.current.isOpenDialogOpen).toBe(true);
    expect(result.current.isOpenConfirmOpen).toBe(false);

    act(() => result.current.setIsOpenDialogOpen(false));
    act(() => store().markDirty());
    act(() => result.current.handleOpen());
    expect(result.current.isOpenConfirmOpen).toBe(true);
    expect(result.current.isOpenDialogOpen).toBe(false);
  });

  it("handleDiscardAndOpen closes the confirmation and opens the dialog", () => {
    const { result } = setup();
    act(() => store().markDirty());
    act(() => result.current.handleOpen());

    act(() => result.current.handleDiscardAndOpen());

    expect(result.current.isOpenConfirmOpen).toBe(false);
    expect(result.current.isOpenDialogOpen).toBe(true);
  });

  it("handleSaveAndOpen closes the confirmation and saves", async () => {
    const { result } = setup();
    act(() => store().markDirty());
    act(() => result.current.handleOpen());

    await act(async () => result.current.handleSaveAndOpen());

    expect(result.current.isOpenConfirmOpen).toBe(false);
    expect(save.handleSaveAndOpen).toHaveBeenCalledTimes(1);
  });
});

describe("save conflict", () => {
  it("opens the conflict dialog when the save hook reports one", () => {
    const { result } = setup();
    act(() => save.lastArgs?.onSaveConflict());
    expect(result.current.isConflictOpen).toBe(true);
  });

  it("reload loads the server version of the current workflow", async () => {
    apiCall.mockResolvedValue(workflow());
    const { result } = setup();
    act(() => store().setWorkflowId(7));
    act(() => save.lastArgs?.onSaveConflict());

    act(() => result.current.handleConflictReload());

    expect(result.current.isConflictOpen).toBe(false);
    await waitFor(() => expect(apiCall).toHaveBeenCalledWith("workflows/7"));
  });

  it("reload without a saved workflow only closes the dialog", () => {
    const { result } = setup();
    act(() => save.lastArgs?.onSaveConflict());
    act(() => result.current.handleConflictReload());
    expect(result.current.isConflictOpen).toBe(false);
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("save-as-new opens Save As, and overwrite saves with overwrite", () => {
    const { result } = setup();
    act(() => save.lastArgs?.onSaveConflict());
    act(() => result.current.handleConflictSaveAsNew());
    expect(result.current.isConflictOpen).toBe(false);
    expect(result.current.isSaveAsOpen).toBe(true);

    act(() => save.lastArgs?.onSaveConflict());
    act(() => result.current.handleConflictOverwrite());
    expect(result.current.isConflictOpen).toBe(false);
    expect(save.handleSave).toHaveBeenCalledWith({ overwrite: true });
  });
});

describe("save as", () => {
  it("beginSaveAsThenRun opens Save As and arms the run, closeSaveAs disarms both", () => {
    const { result } = setup();
    act(() => result.current.beginSaveAsThenRun());
    expect(result.current.isSaveAsOpen).toBe(true);
    expect(result.current.runAfterSave).toBe(true);

    act(() => result.current.closeSaveAs());
    expect(result.current.isSaveAsOpen).toBe(false);
    expect(result.current.runAfterSave).toBe(false);
    expect(result.current.openAfterSave).toBe(false);
  });
});

describe("referential stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender({ mountWorkflowId: null, initialCanvasDraft: null, isPluginsLoading: false, plugins: NO_PLUGINS });
    expect(result.current).toBe(first);
  });
});
