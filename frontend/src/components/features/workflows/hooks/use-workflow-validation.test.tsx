import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";
import { useWorkflowValidation } from "./use-workflow-validation";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const NODES = [{ id: "a" }] as unknown as PersistedCanvasNode[];
const EDGES: WorkflowCanvasEdge[] = [];

const RESULT = {
  findings: [
    { node_id: "a", severity: "error", message: "x" },
    { node_id: "a", severity: "warning", message: "y" },
    { node_id: null, severity: "error", message: "global" },
  ],
};

function setup(workflowId: number | null = 7) {
  const { wrapper } = createQueryWrapper();
  return renderHook(
    (id: number | null) => useWorkflowValidation({ workflowId: id, allNodes: NODES, allEdges: EDGES }),
    { wrapper, initialProps: workflowId },
  );
}

beforeEach(() => {
  apiCall.mockReset();
});

describe("useWorkflowValidation", () => {
  it("posts the draft canvas, stores the result and opens the dialog", async () => {
    apiCall.mockResolvedValue(RESULT);
    const { result } = setup();
    act(() => result.current.handleValidate());
    await waitFor(() => expect(result.current.isDialogOpen).toBe(true));
    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("workflows/7/validate");
    expect(JSON.parse(init.body)).toEqual({ canvas_nodes: NODES, canvas_edges: EDGES });
    expect(result.current.result).toEqual(RESULT);
  });

  it("counts errors and warnings per node and ignores findings without a node", async () => {
    apiCall.mockResolvedValue(RESULT);
    const { result } = setup();
    act(() => result.current.handleValidate());
    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(result.current.validationByNodeId).toEqual({ a: { errorCount: 1, warningCount: 1 } });
  });

  it("does nothing for an unsaved workflow", () => {
    const { result } = setup(null);
    act(() => result.current.handleValidate());
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("forgets the result when another workflow is opened", async () => {
    apiCall.mockResolvedValue(RESULT);
    const { result, rerender } = setup(7);
    act(() => result.current.handleValidate());
    await waitFor(() => expect(result.current.result).not.toBeNull());
    rerender(8);
    expect(result.current.result).toBeNull();
  });

  it("exposes the request error", async () => {
    apiCall.mockRejectedValue(new Error("boom"));
    const { result } = setup();
    act(() => result.current.handleValidate());
    await waitFor(() => expect(result.current.validateError?.message).toBe("boom"));
    expect(result.current.isDialogOpen).toBe(false);
  });

  it("keeps handleValidate stable while nothing it depends on changed", () => {
    const { result, rerender } = setup();
    const first = result.current.handleValidate;
    rerender(7);
    expect(result.current.handleValidate).toBe(first);
  });

  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender(7);
    expect(result.current).toBe(first);
  });
});
