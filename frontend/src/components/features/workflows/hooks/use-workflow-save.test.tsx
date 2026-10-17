import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/hooks/use-api";

import { useWorkflowSave } from "./use-workflow-save";
import type { UseWorkflowSaveOptions } from "./use-workflow-save";

const mutate = vi.fn();

vi.mock("@/hooks/queries/use-workflow-mutations", () => ({
  useWorkflowMutations: () => ({
    createWorkflow: { mutateAsync: vi.fn() },
    updateWorkflow: { mutate, mutateAsync: vi.fn() },
  }),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

function options(overrides: Partial<UseWorkflowSaveOptions> = {}): UseWorkflowSaveOptions {
  return {
    canvas: { allNodes: [], allEdges: [], groups: [], staticAttributes: [] },
    workflowId: 7,
    workflowName: "Backup",
    canvasPayload: {
      canvas_nodes: [],
      canvas_edges: [],
      canvas_groups: [],
      static_attributes: [],
    },
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

beforeEach(() => {
  mutate.mockReset();
});

describe("useWorkflowSave concurrency guard", () => {
  it("sends the loaded updated_at", () => {
    const { result } = renderHook(() => useWorkflowSave(options()));
    result.current.handleSave();
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0].data.expected_updated_at).toBe("2026-10-15T10:00:00.123456Z");
  });

  it("an explicit overwrite sends no expected_updated_at", () => {
    const { result } = renderHook(() => useWorkflowSave(options()));
    result.current.handleSave({ overwrite: true });
    expect(mutate.mock.calls[0][0].data.expected_updated_at).toBeUndefined();
  });

  it("opens the conflict dialog on 409 instead of showing an error", () => {
    const opts = options();
    mutate.mockImplementation((_vars, handlers) => {
      handlers.onError(new ApiError("The workflow was changed", 409));
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.onSaveConflict).toHaveBeenCalledTimes(1);
    expect(opts.markError).not.toHaveBeenCalled();
  });

  it("other errors are still shown", () => {
    const opts = options();
    mutate.mockImplementation((_vars, handlers) => {
      handlers.onError(new ApiError("Server error", 500));
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.onSaveConflict).not.toHaveBeenCalled();
    expect(opts.markError).toHaveBeenCalledWith("Server error");
  });

  it("marks the workflow saved on success", () => {
    const opts = options();
    mutate.mockImplementation((_vars, handlers) => {
      handlers.onSuccess({ git_sync: null, updated_at: "2026-10-15T10:05:00Z" });
    });
    const { result } = renderHook(() => useWorkflowSave(opts));
    result.current.handleSave();
    expect(opts.markSaved).toHaveBeenCalledWith('Saved "Backup"');
  });
});
