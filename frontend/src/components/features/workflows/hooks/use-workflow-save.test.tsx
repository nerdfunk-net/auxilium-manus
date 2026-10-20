import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/hooks/use-api";

import { useWorkflowSave } from "./use-workflow-save";
import type { UseWorkflowSaveOptions } from "./use-workflow-save";

const h = vi.hoisted(() => {
  const mutate = vi.fn();
  const updateMutateAsync = vi.fn();
  const createMutateAsync = vi.fn();
  return {
    mutate,
    updateMutateAsync,
    createMutateAsync,
    toast: vi.fn(),
    // Stable objects: in production `useMutation` returns a new object on every state change,
    // but `mutate` / `mutateAsync` stay the same.
    createWorkflow: { mutateAsync: createMutateAsync },
    updateWorkflow: { mutate, mutateAsync: updateMutateAsync },
    toastApi: { toast: undefined as unknown },
  };
});

vi.mock("@/hooks/queries/use-workflow-mutations", () => ({
  useWorkflowMutations: () => ({
    createWorkflow: h.createWorkflow,
    updateWorkflow: h.updateWorkflow,
  }),
}));
vi.mock("@/hooks/use-toast", () => {
  const api = { toast: h.toast };
  return { useToast: () => api };
});

const CANVAS = { allNodes: [], allEdges: [], groups: [], staticAttributes: [] };
const BAD_CANVAS = {
  ...CANVAS,
  staticAttributes: [{ name: " ", type: "string", default: "" }],
};
const PAYLOAD = {
  canvas_nodes: [],
  canvas_edges: [],
  canvas_groups: [],
  static_attributes: [],
};

function options(overrides: Partial<UseWorkflowSaveOptions> = {}): UseWorkflowSaveOptions {
  return {
    canvas: CANVAS,
    workflowId: 7,
    workflowName: "Backup",
    canvasPayload: PAYLOAD,
    markSaved: vi.fn(),
    markError: vi.fn(),
    loadWorkflow: vi.fn(),
    setIsSaveAsOpen: vi.fn(),
    openAfterSave: false,
    runAfterSave: false,
    setOpenAfterSave: vi.fn(),
    setRunAfterSave: vi.fn(),
    setIsOpenDialogOpen: vi.fn(),
    requestRunRef: { current: vi.fn() },
    baselineUpdatedAtRef: { current: "2026-10-15T10:00:00.123456Z" },
    onSaveConflict: vi.fn(),
    ...overrides,
  } as unknown as UseWorkflowSaveOptions;
}

const FORM = { name: "Backup", visibility: "private" as const };
const SAVED = {
  id: 9,
  uuid: "u-9",
  name: "Backup",
  description: "d",
  folder: "/net",
  visibility: "public",
  is_version_controlled: true,
  notes: "n",
  git_sync: null,
};

beforeEach(() => {
  h.mutate.mockReset();
  h.updateMutateAsync.mockReset();
  h.createMutateAsync.mockReset();
  h.toast.mockReset();
});

describe("useWorkflowSave concurrency guard", () => {
  it("sends the loaded updated_at", () => {
    const { result } = renderHook(() => useWorkflowSave(options()));
    result.current.handleSave();
    expect(h.mutate).toHaveBeenCalledTimes(1);
    expect(h.mutate.mock.calls[0][0].data.expected_updated_at).toBe("2026-10-15T10:00:00.123456Z");
  });

  it("an explicit overwrite sends no expected_updated_at", () => {
    const { result } = renderHook(() => useWorkflowSave(options()));
    result.current.handleSave({ overwrite: true });
    expect(h.mutate.mock.calls[0][0].data.expected_updated_at).toBeUndefined();
  });

  it("opens the conflict dialog on 409 instead of showing an error", () => {
    const opts = options();
    h.mutate.mockImplementation((_vars, handlers) => {
      handlers.onError(new ApiError("The workflow was changed", 409));
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.onSaveConflict).toHaveBeenCalledTimes(1);
    expect(opts.markError).not.toHaveBeenCalled();
  });

  it("other errors are still shown", () => {
    const opts = options();
    h.mutate.mockImplementation((_vars, handlers) => {
      handlers.onError(new ApiError("Server error", 500));
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.onSaveConflict).not.toHaveBeenCalled();
    expect(opts.markError).toHaveBeenCalledWith("Server error");
  });

  it("marks the workflow saved on success", () => {
    const opts = options();
    h.mutate.mockImplementation((_vars, handlers) => {
      handlers.onSuccess({ git_sync: null, updated_at: "2026-10-15T10:05:00Z" });
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.markSaved).toHaveBeenCalledWith('Saved "Backup"');
  });
});

describe("useWorkflowSave handleSave", () => {
  it("opens Save As for a workflow that was never saved", () => {
    const opts = options({ workflowId: null });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.setIsSaveAsOpen).toHaveBeenCalledWith(true);
    expect(h.mutate).not.toHaveBeenCalled();
  });

  it("refuses an invalid canvas and says why", () => {
    const opts = options({ canvas: BAD_CANVAS } as never);
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.markError).toHaveBeenCalledWith(
      "Cannot save: A static attribute is missing a name.",
    );
    expect(h.mutate).not.toHaveBeenCalled();
  });

  it("sends no expected_updated_at when no baseline is known", () => {
    const opts = options({ baselineUpdatedAtRef: { current: null } });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(h.mutate.mock.calls[0][0].data.expected_updated_at).toBeUndefined();
  });

  it("warns when the Git sync failed after a successful save", () => {
    const opts = options();
    h.mutate.mockImplementation((_v, handlers) =>
      handlers.onSuccess({ git_sync: { status: "failed", message: "push rejected" } }),
    );
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.markSaved).toHaveBeenCalled();
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Saved, but Git sync failed", description: "push rejected" }),
    );
  });

  it("does not warn when the Git sync worked or was not attempted", () => {
    const opts = options();
    h.mutate.mockImplementation((_v, handlers) =>
      handlers.onSuccess({ git_sync: { status: "synced", message: null } }),
    );
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(h.toast).not.toHaveBeenCalled();
  });

  it("uses a generic message for an error that is not an Error", () => {
    const opts = options();
    h.mutate.mockImplementation((_v, handlers) => handlers.onError("nope"));
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.markError).toHaveBeenCalledWith("Failed to save workflow");
  });
});

describe("useWorkflowSave handleSaveAs", () => {
  it("creates the workflow with the canvas payload and loads the result", async () => {
    h.createMutateAsync.mockResolvedValue(SAVED);
    const opts = options({ workflowId: null });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs({ ...FORM, description: "d", folder: "/net" });
    expect(h.createMutateAsync).toHaveBeenCalledWith({
      name: "Backup",
      description: "d",
      folder: "/net",
      visibility: "private",
      is_version_controlled: undefined,
      ...PAYLOAD,
    });
    expect(opts.loadWorkflow).toHaveBeenCalledWith({
      workflowId: 9,
      workflowUuid: "u-9",
      workflowName: "Backup",
      workflowDescription: "d",
      workflowFolder: "/net",
      workflowVisibility: "public",
      workflowIsVersionControlled: true,
      workflowNotes: "n",
    });
    expect(opts.setIsSaveAsOpen).toHaveBeenCalledWith(false);
    expect(opts.markSaved).toHaveBeenCalledWith('Saved as "Backup"');
  });

  it("fills in defaults for the optional fields the server leaves out", async () => {
    h.createMutateAsync.mockResolvedValue({
      ...SAVED,
      uuid: undefined,
      description: null,
      folder: null,
      notes: undefined,
    });
    const opts = options({ workflowId: null });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(opts.loadWorkflow).toHaveBeenCalledWith(
      expect.objectContaining({
        workflowUuid: null,
        workflowDescription: "",
        workflowFolder: "/",
        workflowNotes: null,
      }),
    );
  });

  it("opens the Open dialog afterwards when Save & open started the flow", async () => {
    h.createMutateAsync.mockResolvedValue(SAVED);
    const opts = options({ workflowId: null, openAfterSave: true });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(opts.setOpenAfterSave).toHaveBeenCalledWith(false);
    expect(opts.setIsOpenDialogOpen).toHaveBeenCalledWith(true);
    expect(opts.requestRunRef.current).not.toHaveBeenCalled();
  });

  it("requests the run afterwards when Save & run started the flow", async () => {
    h.createMutateAsync.mockResolvedValue(SAVED);
    const opts = options({ workflowId: null, runAfterSave: true });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(opts.setRunAfterSave).toHaveBeenCalledWith(false);
    expect(opts.requestRunRef.current).toHaveBeenCalledWith(9);
    expect(opts.setIsOpenDialogOpen).not.toHaveBeenCalled();
  });

  it("does nothing after the save when neither flow was pending", async () => {
    h.createMutateAsync.mockResolvedValue(SAVED);
    const opts = options({ workflowId: null });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(opts.setOpenAfterSave).not.toHaveBeenCalled();
    expect(opts.setRunAfterSave).not.toHaveBeenCalled();
    expect(opts.requestRunRef.current).not.toHaveBeenCalled();
  });

  it("warns about a failed Git sync", async () => {
    h.createMutateAsync.mockResolvedValue({ ...SAVED, git_sync: { status: "failed", message: null } });
    const { result } = renderHook(() => useWorkflowSave(options({ workflowId: null })));
    await result.current.handleSaveAs(FORM);
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({
        description: "The workflow was saved, but committing to Git failed.",
      }),
    );
  });

  it("refuses an invalid canvas without calling the server", async () => {
    const opts = options({ workflowId: null, canvas: BAD_CANVAS } as never);
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(h.createMutateAsync).not.toHaveBeenCalled();
    expect(opts.markError).toHaveBeenCalledWith(expect.stringMatching(/^Cannot save: /));
  });

  it("reports a failed create and leaves the dialog and the pending flows alone", async () => {
    h.createMutateAsync.mockRejectedValue(new Error("name taken"));
    const opts = options({ workflowId: null, runAfterSave: true, openAfterSave: true });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAs(FORM);
    expect(opts.markError).toHaveBeenCalledWith("name taken");
    expect(opts.setIsSaveAsOpen).not.toHaveBeenCalled();
    expect(opts.loadWorkflow).not.toHaveBeenCalled();
    expect(opts.requestRunRef.current).not.toHaveBeenCalled();
    expect(opts.setIsOpenDialogOpen).not.toHaveBeenCalled();
  });
});

describe("useWorkflowSave handleOverwrite", () => {
  it("replaces the chosen workflow without a concurrency guard", async () => {
    h.updateMutateAsync.mockResolvedValue(SAVED);
    // A workflow is loaded (id 7) and the user overwrites a different one (id 42).
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleOverwrite(FORM, 42);
    const call = h.updateMutateAsync.mock.calls[0][0];
    expect(call.id).toBe(42);
    expect(call.data).toEqual(expect.objectContaining({ name: "Backup", ...PAYLOAD }));
    expect(call.data).not.toHaveProperty("expected_updated_at");
    expect(opts.loadWorkflow).toHaveBeenCalledWith(expect.objectContaining({ workflowId: 9 }));
    expect(opts.setIsSaveAsOpen).toHaveBeenCalledWith(false);
    expect(opts.markSaved).toHaveBeenCalledWith('Saved as "Backup"');
  });

  it("refuses an invalid canvas", async () => {
    const opts = options({ canvas: BAD_CANVAS } as never);
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleOverwrite(FORM, 42);
    expect(h.updateMutateAsync).not.toHaveBeenCalled();
    expect(opts.markError).toHaveBeenCalled();
  });

  it("reports a failure with its own fallback text", async () => {
    h.updateMutateAsync.mockRejectedValue("x");
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleOverwrite(FORM, 42);
    expect(opts.markError).toHaveBeenCalledWith("Failed to overwrite workflow");
    expect(opts.loadWorkflow).not.toHaveBeenCalled();
  });
});

describe("useWorkflowSave handleSaveAndOpen", () => {
  it("asks for a name first when the workflow was never saved", async () => {
    const opts = options({ workflowId: null });
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(opts.setOpenAfterSave).toHaveBeenCalledWith(true);
    expect(opts.setIsSaveAsOpen).toHaveBeenCalledWith(true);
    expect(h.updateMutateAsync).not.toHaveBeenCalled();
  });

  it("saves with the concurrency guard, then opens the Open dialog", async () => {
    h.updateMutateAsync.mockResolvedValue(SAVED);
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(h.updateMutateAsync).toHaveBeenCalledWith({
      id: 7,
      data: { ...PAYLOAD, expected_updated_at: "2026-10-15T10:00:00.123456Z" },
    });
    expect(opts.markSaved).toHaveBeenCalledWith('Saved "Backup"');
    expect(opts.setIsOpenDialogOpen).toHaveBeenCalledWith(true);
  });

  it("warns about a failed Git sync before opening", async () => {
    h.updateMutateAsync.mockResolvedValue({ ...SAVED, git_sync: { status: "failed", message: "x" } });
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(h.toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Saved, but Git sync failed" }),
    );
    expect(opts.setIsOpenDialogOpen).toHaveBeenCalledWith(true);
  });

  it("refuses an invalid canvas", async () => {
    const opts = options({ canvas: BAD_CANVAS } as never);
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(h.updateMutateAsync).not.toHaveBeenCalled();
    expect(opts.setIsOpenDialogOpen).not.toHaveBeenCalled();
  });

  it("opens the conflict dialog on 409 and does not open the Open dialog", async () => {
    h.updateMutateAsync.mockRejectedValue(new ApiError("changed", 409));
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(opts.onSaveConflict).toHaveBeenCalledTimes(1);
    expect(opts.markError).not.toHaveBeenCalled();
    expect(opts.setIsOpenDialogOpen).not.toHaveBeenCalled();
  });

  it("shows other errors and does not open the Open dialog", async () => {
    h.updateMutateAsync.mockRejectedValue(new ApiError("down", 503));
    const opts = options();
    const { result } = renderHook(() => useWorkflowSave(opts));
    await result.current.handleSaveAndOpen();
    expect(opts.markError).toHaveBeenCalledWith("down");
    expect(opts.onSaveConflict).not.toHaveBeenCalled();
    expect(opts.setIsOpenDialogOpen).not.toHaveBeenCalled();
  });
});

describe("useWorkflowSave stability", () => {
  it("returns the same object when nothing changed", () => {
    const opts = options();
    const { result, rerender } = renderHook(() => useWorkflowSave(opts));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("keeps its handlers when only the mutation state object changes", () => {
    const opts = options();
    const { result, rerender } = renderHook(() => useWorkflowSave(opts));
    const { handleSave, handleSaveAs, handleOverwrite, handleSaveAndOpen } = result.current;
    // `useMutation` hands out a new object whenever its state changes (isPending, data, ...).
    h.updateWorkflow = { ...h.updateWorkflow };
    h.createWorkflow = { ...h.createWorkflow };
    rerender();
    expect(result.current.handleSave).toBe(handleSave);
    expect(result.current.handleSaveAs).toBe(handleSaveAs);
    expect(result.current.handleOverwrite).toBe(handleOverwrite);
    expect(result.current.handleSaveAndOpen).toBe(handleSaveAndOpen);
  });
});
