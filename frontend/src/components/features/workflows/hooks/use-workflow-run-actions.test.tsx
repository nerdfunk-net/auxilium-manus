import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";

import { useWorkflowBuilderStore } from "./use-workflow-builder-store";
import { useWorkflowRunActions } from "./use-workflow-run-actions";
import type { UseWorkflowRunActionsOptions } from "./use-workflow-run-actions";

const h = vi.hoisted(() => ({
  push: vi.fn(),
  router: { push: vi.fn() },
  settings: { data: undefined as { switch_to_runs_on_start?: boolean } | undefined },
  mutateAsync: vi.fn(),
  isPending: false,
  fetchQuery: vi.fn(),
  apiCall: vi.fn(),
}));

// The real useQueryClient returns one stable client; the mock must too.
const stableQueryClient = {
  fetchQuery: (opts: { queryFn: () => unknown }) => h.fetchQuery(opts),
};
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => stableQueryClient }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));

vi.mock("next/navigation", () => ({ useRouter: () => h.router }));
vi.mock("@/hooks/queries/use-client-settings-query", () => ({
  useClientSettingsQuery: () => h.settings,
}));
vi.mock("@/hooks/queries/use-workflow-run-mutations", () => ({
  // A fresh object per render, like TanStack's useMutation.
  useTriggerRunMutation: () => ({ mutateAsync: h.mutateAsync, isPending: h.isPending }),
}));

const executableNode = { id: "n1", data: { kind: "get-config", title: "Get" } };
const getFromUser = (param: string) => ({
  id: "u1",
  data: { kind: "get-from-user", title: "Ask", pluginConfig: { device_param: param } },
});

interface Harness {
  options: UseWorkflowRunActionsOptions;
  updateMutateAsync: ReturnType<typeof vi.fn>;
  handleStaticAttributesChange: ReturnType<typeof vi.fn>;
  beginSaveAsThenRun: ReturnType<typeof vi.fn>;
}

function harness(
  canvas: Record<string, unknown> = {},
  persistence: Record<string, unknown> = {},
): Harness {
  const updateMutateAsync = vi.fn().mockResolvedValue({});
  const handleStaticAttributesChange = vi.fn();
  const beginSaveAsThenRun = vi.fn();
  const stableCanvas = {
    allNodes: [executableNode],
    allEdges: [],
    groups: [],
    staticAttributes: [],
    handleStaticAttributesChange,
    ...canvas,
  };
  const stablePersistence = {
    beginSaveAsThenRun,
    updateWorkflow: { mutateAsync: updateMutateAsync },
    workflowId: 7,
    workflowName: "Backup",
    ...persistence,
  };
  return {
    options: {
      canvas: stableCanvas,
      persistence: stablePersistence,
    } as unknown as UseWorkflowRunActionsOptions,
    updateMutateAsync,
    handleStaticAttributesChange,
    beginSaveAsThenRun,
  };
}

const status = () => useWorkflowBuilderStore.getState();

beforeEach(() => {
  h.router.push.mockReset();
  h.mutateAsync.mockReset().mockResolvedValue({ id: 55 });
  h.settings.data = undefined;
  h.isPending = false;
  h.apiCall.mockReset();
  h.fetchQuery.mockReset().mockImplementation(async (opts: { queryFn: () => unknown }) => opts.queryFn());
  useWorkflowBuilderStore.setState({
    isDirty: false,
    workflowStatus: "Draft",
    lastAction: "",
    activeRunId: null,
  });
});

describe("useWorkflowRunActions.dispatchRun", () => {
  it("posts a manual run with the inputs and marks the run queued", async () => {
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.dispatchRun(9, { region: "eu" }));
    expect(h.mutateAsync).toHaveBeenCalledWith({
      device_ids: [],
      trigger_type: "manual",
      workflowId: 9,
      run_inputs: { region: "eu" },
    });
    expect(status().activeRunId).toBe(55);
    expect(status().workflowStatus).toBe("Running");
    expect(status().lastAction).toBe("Run queued");
  });

  it("switches to the runs page by default, and when the setting is on", async () => {
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.dispatchRun(9, {}));
    expect(h.router.push).toHaveBeenCalledWith("/workflows/runs");

    h.router.push.mockReset();
    h.settings.data = { switch_to_runs_on_start: true };
    const second = renderHook(() => useWorkflowRunActions(options));
    await act(() => second.result.current.dispatchRun(9, {}));
    expect(h.router.push).toHaveBeenCalledTimes(1);
  });

  it("stays on the builder when the user turned the switch off", async () => {
    h.settings.data = { switch_to_runs_on_start: false };
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.dispatchRun(9, {}));
    expect(h.router.push).not.toHaveBeenCalled();
    expect(status().workflowStatus).toBe("Running");
  });

  it("shows the error message when the run cannot be triggered", async () => {
    h.mutateAsync.mockRejectedValue(new Error("Hatchet is down"));
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.dispatchRun(9, {}));
    expect(status().workflowStatus).toBe("Error");
    expect(status().lastAction).toBe("Hatchet is down");
    expect(status().activeRunId).toBeNull();
    expect(h.router.push).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for a non-Error rejection", async () => {
    h.mutateAsync.mockRejectedValue("boom");
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.dispatchRun(9, {}));
    expect(status().lastAction).toBe("Failed to trigger run");
  });
});

describe("useWorkflowRunActions.requestRun", () => {
  it("refuses to run an unsaved workflow", async () => {
    const { options } = harness({}, { workflowId: null });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(status().lastAction).toBe("Save the workflow before running");
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("an override id wins over the open workflow", async () => {
    const { options } = harness({}, { workflowId: null });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun(12));
    expect(h.mutateAsync.mock.calls[0][0].workflowId).toBe(12);
  });

  it("blocks a run on a validation issue and names the first one", async () => {
    const { options } = harness({ allNodes: [] });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(status().lastAction).toBe("Cannot run: Workflow has no steps.");
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("skipValidation runs a workflow the canvas would not validate", async () => {
    const { options } = harness({ allNodes: [] });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun(undefined, { skipValidation: true }));
    expect(h.mutateAsync).toHaveBeenCalledTimes(1);
  });

  it("dispatches straight away when the workflow declares no run inputs", async () => {
    const { options, updateMutateAsync } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(h.mutateAsync.mock.calls[0][0].run_inputs).toEqual({});
    expect(updateMutateAsync).not.toHaveBeenCalled();
    expect(result.current.isRunInputsDialogOpen).toBe(false);
  });

  it("persists the schema and opens the inputs dialog instead of running", async () => {
    const { options, updateMutateAsync, handleStaticAttributesChange } = harness({
      allNodes: [executableNode, getFromUser("site")],
    });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: 7,
      data: { static_attributes: [{ name: "site", type: "string", required: true }] },
    });
    expect(handleStaticAttributesChange).toHaveBeenCalledWith([
      { name: "site", type: "string", required: true },
    ]);
    expect(result.current.isRunInputsDialogOpen).toBe(true);
    expect(result.current.pendingRunTargetId).toBe(7);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not rewrite the canvas attributes when they already match", async () => {
    const attrs = [{ name: "site", type: "string", required: true }];
    const { options, handleStaticAttributesChange } = harness({
      allNodes: [executableNode, getFromUser("site")],
      staticAttributes: attrs,
    });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(handleStaticAttributesChange).not.toHaveBeenCalled();
    expect(result.current.isRunInputsDialogOpen).toBe(true);
  });

  it("stops and shows the error when the schema cannot be persisted", async () => {
    const { options, updateMutateAsync } = harness({
      allNodes: [executableNode, getFromUser("site")],
    });
    updateMutateAsync.mockRejectedValue(new Error("403 forbidden"));
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(status().lastAction).toBe("403 forbidden");
    expect(result.current.isRunInputsDialogOpen).toBe(false);
    expect(result.current.pendingRunTargetId).toBeNull();
  });

  it("uses a readable fallback when the schema sync fails without an Error", async () => {
    const { options, updateMutateAsync } = harness({
      allNodes: [executableNode, getFromUser("site")],
    });
    updateMutateAsync.mockRejectedValue(undefined);
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.requestRun());
    expect(status().lastAction).toBe("Failed to sync run parameters on the workflow");
  });
});

describe("useWorkflowRunActions run-inputs dialog", () => {
  async function openDialog() {
    const harnessed = harness({ allNodes: [executableNode, getFromUser("site")] });
    const rendered = renderHook(() => useWorkflowRunActions(harnessed.options));
    await act(() => rendered.result.current.requestRun());
    return rendered;
  }

  it("submitting closes the dialog, runs the pending target and clears it", async () => {
    const { result } = await openDialog();
    await act(() => result.current.handleRunInputsSubmit({ site: "ber" }));
    expect(h.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ workflowId: 7, run_inputs: { site: "ber" } }),
    );
    expect(result.current.isRunInputsDialogOpen).toBe(false);
    expect(result.current.pendingRunTargetId).toBeNull();
  });

  it("a submit without a pending target does nothing", async () => {
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(() => result.current.handleRunInputsSubmit({ site: "ber" }));
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("dismissing the dialog forgets the pending target", async () => {
    const { result } = await openDialog();
    act(() => result.current.setIsRunInputsDialogOpen(false));
    expect(result.current.isRunInputsDialogOpen).toBe(false);
    expect(result.current.pendingRunTargetId).toBeNull();
  });

  it("a failed run after submit shows the error and still clears the target", async () => {
    const { result } = await openDialog();
    h.mutateAsync.mockRejectedValue(new Error("queue full"));
    await act(() => result.current.handleRunInputsSubmit({ site: "ber" }));
    expect(status().lastAction).toBe("queue full");
    expect(result.current.pendingRunTargetId).toBeNull();
  });

  it("exposes the merged run input attributes", async () => {
    const { result } = await openDialog();
    expect(result.current.runInputAttributes).toEqual([
      { name: "site", type: "string", required: true },
    ]);
  });
});

describe("useWorkflowRunActions.handleRun", () => {
  it("asks first for an unsaved workflow", () => {
    const { options } = harness({}, { workflowId: null });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    act(() => result.current.handleRun());
    expect(result.current.isRunConfirmOpen).toBe(true);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("asks first when there are unsaved changes", () => {
    useWorkflowBuilderStore.setState({ isDirty: true });
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    act(() => result.current.handleRun());
    expect(result.current.isRunConfirmOpen).toBe(true);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("runs a clean saved workflow without asking", async () => {
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRun());
    expect(result.current.isRunConfirmOpen).toBe(false);
    expect(h.mutateAsync).toHaveBeenCalledTimes(1);
  });
});

describe("useWorkflowRunActions.handleSaveAndRun", () => {
  beforeEach(() => {
    useWorkflowBuilderStore.setState({ isDirty: true });
  });

  // The hook reads isDirty from the store, so it must be set before the hook renders.
  async function confirmOpen(rendered: { result: { current: { handleRun: () => void; isRunConfirmOpen: boolean } } }) {
    act(() => rendered.result.current.handleRun());
    expect(rendered.result.current.isRunConfirmOpen).toBe(true);
  }

  it("an unsaved workflow goes through Save As and does not run yet", async () => {
    const { options, beginSaveAsThenRun } = harness({}, { workflowId: null });
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(beginSaveAsThenRun).toHaveBeenCalledTimes(1);
    expect(rendered.result.current.isRunConfirmOpen).toBe(false);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("saves the whole canvas, marks it saved, then runs", async () => {
    const { options, updateMutateAsync } = harness();
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(updateMutateAsync).toHaveBeenCalledWith({
      id: 7,
      data: {
        canvas_nodes: [executableNode],
        canvas_edges: [],
        canvas_groups: [],
        static_attributes: [],
      },
    });
    expect(status().isDirty).toBe(false);
    expect(h.mutateAsync).toHaveBeenCalledTimes(1);
    expect(status().lastAction).toBe("Run queued");
  });

  it("writes the run-input schema once: the save carries it, the run does not repeat it", async () => {
    const { options, updateMutateAsync } = harness({ allNodes: [executableNode, getFromUser("region")] });
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(updateMutateAsync).toHaveBeenCalledTimes(1);
    expect(updateMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          static_attributes: [{ name: "region", type: "string", required: true }],
        }),
      }),
    );
    // The inputs dialog still opens for the declared parameter.
    expect(rendered.result.current.isRunInputsDialogOpen).toBe(true);
    expect(rendered.result.current.pendingRunTargetId).toBe(7);
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("does not save or run when the canvas is invalid", async () => {
    const { options, updateMutateAsync } = harness({ allNodes: [] });
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(status().lastAction).toBe("Cannot save: Workflow has no steps.");
    expect(updateMutateAsync).not.toHaveBeenCalled();
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("a failed save shows the error and never runs", async () => {
    const { options, updateMutateAsync } = harness();
    updateMutateAsync.mockRejectedValue(new Error("conflict"));
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(status().lastAction).toBe("conflict");
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("a save fallback message covers a non-Error rejection", async () => {
    const { options, updateMutateAsync } = harness();
    updateMutateAsync.mockRejectedValue(null);
    const rendered = renderHook(() => useWorkflowRunActions(options));
    await confirmOpen(rendered);
    await act(() => rendered.result.current.handleSaveAndRun());
    expect(status().lastAction).toBe("Failed to save workflow");
  });
});

describe("useWorkflowRunActions.handleRunSavedVersion", () => {
  const saved = (over: Record<string, unknown> = {}) => ({
    canvas_nodes: [executableNode],
    static_attributes: [],
    ...over,
  });

  it("closes the confirm dialog and runs the saved version without validating the canvas", async () => {
    h.apiCall.mockResolvedValue(saved());
    const { options } = harness({ allNodes: [] });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    act(() => result.current.setIsRunConfirmOpen(true));
    await act(async () => result.current.handleRunSavedVersion());
    expect(result.current.isRunConfirmOpen).toBe(false);
    expect(h.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ workflowId: 7, run_inputs: {} }),
    );
  });

  it("an unsaved workflow cannot run a saved version", async () => {
    const { options } = harness({}, { workflowId: null });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(status().lastAction).toBe("Save the workflow before running");
    expect(h.apiCall).not.toHaveBeenCalled();
  });

  it("ignores a get-from-user step that is only on the dirty canvas", async () => {
    h.apiCall.mockResolvedValue(saved());
    const { options, updateMutateAsync } = harness({ allNodes: [executableNode, getFromUser("region")] });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(h.apiCall).toHaveBeenCalledWith("workflows/7");
    // Always the stored version, never a cached copy.
    expect(h.fetchQuery).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: queryKeys.workflows.detail(7), staleTime: 0 }),
    );
    expect(result.current.isRunInputsDialogOpen).toBe(false);
    expect(h.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ run_inputs: {} }));
    expect(updateMutateAsync).not.toHaveBeenCalled();
  });

  it("asks for the saved inputs even when the canvas removed that step, and never writes the workflow", async () => {
    h.apiCall.mockResolvedValue(saved({ canvas_nodes: [executableNode, getFromUser("region")] }));
    const { options, updateMutateAsync, handleStaticAttributesChange } = harness({
      allNodes: [executableNode],
    });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(result.current.isRunInputsDialogOpen).toBe(true);
    expect(result.current.pendingRunTargetId).toBe(7);
    expect(result.current.runInputAttributes.map((a) => a.name)).toEqual(["region"]);
    expect(updateMutateAsync).not.toHaveBeenCalled();
    expect(handleStaticAttributesChange).not.toHaveBeenCalled();
    expect(h.mutateAsync).not.toHaveBeenCalled();

    await act(async () => result.current.handleRunInputsSubmit({ region: "eu" }));
    expect(h.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ workflowId: 7, run_inputs: { region: "eu" } }),
    );
  });

  it("uses the saved static attributes, not the canvas ones", async () => {
    h.apiCall.mockResolvedValue(
      saved({ static_attributes: [{ name: "site", type: "string", required: false }] }),
    );
    const { options } = harness({
      staticAttributes: [{ name: "other", type: "string", required: true }],
    });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(result.current.runInputAttributes.map((a) => a.name)).toEqual(["site"]);
  });

  it("goes back to the canvas attributes after the dialog closes", async () => {
    h.apiCall.mockResolvedValue(saved({ canvas_nodes: [getFromUser("region")] }));
    const { options } = harness({ allNodes: [executableNode] });
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    act(() => result.current.setIsRunInputsDialogOpen(false));
    expect(result.current.runInputAttributes).toEqual([]);
    expect(result.current.pendingRunTargetId).toBeNull();
  });

  it("shows an error and does not run when the saved workflow cannot be loaded", async () => {
    h.apiCall.mockRejectedValue(new Error("gone"));
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(status().workflowStatus).toBe("Error");
    expect(status().lastAction).toBe("gone");
    expect(h.mutateAsync).not.toHaveBeenCalled();
  });

  it("treats a saved workflow without nodes or attributes as having no inputs", async () => {
    h.apiCall.mockResolvedValue({ canvas_nodes: null, static_attributes: null });
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    await act(async () => result.current.handleRunSavedVersion());
    expect(h.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({ run_inputs: {} }));
  });
});

describe("useWorkflowRunActions stability", () => {
  it("exposes whether a run is being triggered", () => {
    h.isPending = true;
    const { options } = harness();
    const { result } = renderHook(() => useWorkflowRunActions(options));
    expect(result.current.isTriggeringRun).toBe(true);
  });

  it("returns the same object when nothing changed", () => {
    const { options } = harness();
    const { result, rerender } = renderHook(() => useWorkflowRunActions(options));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
