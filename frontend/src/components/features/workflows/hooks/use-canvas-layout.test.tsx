import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CanvasGroup, PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";
import { projectCanvasView } from "../utils/canvas-group-projection";
import { useCanvasLayout } from "./use-canvas-layout";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

const runAutoLayout = vi.hoisted(() => vi.fn());
vi.mock("../utils/auto-layout", () => ({ runAutoLayout }));

const markDirty = vi.fn();
const requestFitView = vi.fn();
const toast = vi.fn();

beforeEach(() => {
  markDirty.mockReset();
  requestFitView.mockReset();
  toast.mockReset();
  runAutoLayout.mockReset();
});

function node(id: string, x = 0, y = 0, data: Record<string, unknown> = {}): PersistedCanvasNode {
  return {
    id,
    type: "workflowNode",
    position: { x, y },
    width: 100,
    height: 50,
    data: { kind: "step", title: id, ...data },
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string, data: Record<string, unknown> = {}) {
  return { id, source, target, type: "waypoint", data } as unknown as WorkflowCanvasEdge;
}

function group(id: string, nodeIds: string[], extra: Partial<CanvasGroup> = {}): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 500, y: 500 }, parentGroupId: null, ...extra };
}

interface Seed {
  nodes?: PersistedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  groups?: CanvasGroup[];
}

/** Real React state with the real group projection, like useWorkflowCanvasCore. */
function setup(seed: Seed = {}) {
  return renderHook(() => {
    const [allNodes, setAllNodes] = useState(seed.nodes ?? []);
    const [allEdges, setAllEdges] = useState(seed.edges ?? []);
    const [groups, setGroups] = useState(seed.groups ?? []);
    const projected = projectCanvasView(allNodes, allEdges, groups, null);
    const core = {
      projected,
      allNodes,
      setAllNodes,
      setAllEdges,
      setGroups,
      markDirty,
      requestFitView,
      toast,
    } as unknown as UseWorkflowCanvasCoreResult;
    return { layout: useCanvasLayout(core), allNodes, allEdges, groups, projected };
  });
}

const nodeById = (nodes: PersistedCanvasNode[], id: string) => nodes.find((n) => n.id === id)!;

describe("edge editing", () => {
  const seed = { nodes: [node("a"), node("b")], edges: [edge("e1", "a", "b", { label: "keep" })] };

  it("changes the style of an edge and keeps its other data", () => {
    const { result } = setup(seed);
    act(() => result.current.layout.handleEdgeStyleChange("e1", "straight" as never));
    expect(result.current.allEdges[0].data).toEqual({ label: "keep", edgeStyle: "straight" });
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["handleEdgeLabelChange", "label", "hello"],
    ["handleEdgeStartLabelChange", "startLabel", "from"],
    ["handleEdgeEndLabelChange", "endLabel", "to"],
    ["handleEdgeLabelBoldChange", "labelBold", true],
    ["handleEdgeLabelFontSizeChange", "labelFontSize", 18],
  ] as const)("%s sets %s", (handler, field, value) => {
    const { result } = setup(seed);
    act(() => (result.current.layout[handler] as (id: string, v: unknown) => void)("e1", value));
    expect(result.current.allEdges[0].data).toMatchObject({ label: expect.anything(), [field]: value });
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("edits only the targeted edge", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c")],
      edges: [edge("e1", "a", "b"), edge("e2", "b", "c")],
    });
    act(() => result.current.layout.handleEdgeLabelChange("e2", "x"));
    expect(result.current.allEdges[0].data).toEqual({});
    expect(result.current.allEdges[1].data).toEqual({ label: "x" });
  });

  it("resolves a proxy edge of a collapsed group to the real edge", () => {
    const { result } = setup({
      nodes: [node("src"), node("m1"), node("m2")],
      edges: [edge("e1", "src", "m1")],
      groups: [group("g1", ["m1", "m2"])],
    });
    const proxy = result.current.projected.edges[0];
    expect(proxy.id).not.toBe("e1");

    act(() => result.current.layout.handleEdgeLabelChange(proxy.id, "via group"));

    expect(result.current.allEdges[0].data).toMatchObject({ label: "via group" });
  });
});

describe("node editing", () => {
  const seed = { nodes: [node("a"), node("b"), node("c")] };

  it("renames only the targeted node", () => {
    const { result } = setup(seed);
    act(() => result.current.layout.handleNodeTitleChange("b", "Renamed"));
    expect(result.current.allNodes.map((n) => n.data.title)).toEqual(["a", "Renamed", "c"]);
    expect(markDirty).toHaveBeenCalled();
  });

  it("disables one node, or several at once", () => {
    const { result } = setup(seed);
    act(() => result.current.layout.handleNodeDisabledChange("a", true));
    expect(result.current.allNodes.map((n) => n.data.disabled)).toEqual([true, undefined, undefined]);

    act(() => result.current.layout.handleNodesDisabledChange(["b", "c"], true));
    expect(result.current.allNodes.map((n) => n.data.disabled)).toEqual([true, true, true]);

    act(() => result.current.layout.handleNodesDisabledChange(["a", "c"], false));
    expect(result.current.allNodes.map((n) => n.data.disabled)).toEqual([false, true, false]);
  });

  it("does not mutate the previous node objects", () => {
    const original = node("a");
    const snapshot = structuredClone(original);
    const { result } = setup({ nodes: [original] });
    act(() => result.current.layout.handleNodeTitleChange("a", "x"));
    expect(original).toEqual(snapshot);
  });
});

describe("handle sides", () => {
  it("sets the income side of a node", () => {
    const { result } = setup({ nodes: [node("a")] });
    act(() => result.current.layout.handleIncomeHandleSideChange("a", "top"));
    expect(nodeById(result.current.allNodes, "a").data).toMatchObject({ incomeHandleSide: "top" });
  });

  it("swaps the sides when the income side is moved onto the outcome side", () => {
    // defaults: income left, outcome right
    const { result } = setup({ nodes: [node("a")] });
    act(() => result.current.layout.handleIncomeHandleSideChange("a", "right"));
    expect(nodeById(result.current.allNodes, "a").data).toMatchObject({
      incomeHandleSide: "right",
      outcomeHandleSide: "left",
    });
  });

  it("sets the outcome side of a node", () => {
    const { result } = setup({ nodes: [node("a")] });
    act(() => result.current.layout.handleOutcomeHandleSideChange("a", "bottom"));
    expect(nodeById(result.current.allNodes, "a").data).toMatchObject({ outcomeHandleSide: "bottom" });
  });

  it("stores the handle sides of a collapsed group on the group, with the same swap rule", () => {
    const { result } = setup({
      nodes: [node("m1"), node("m2")],
      groups: [group("g1", ["m1", "m2"])],
    });
    act(() => result.current.layout.handleIncomeHandleSideChange("__group__g1", "right"));
    expect(result.current.groups[0]).toMatchObject({ incomeHandleSide: "right", outcomeHandleSide: "left" });

    act(() => result.current.layout.handleOutcomeHandleSideChange("__group__g1", "top"));
    expect(result.current.groups[0].outcomeHandleSide).toBe("top");
    expect(result.current.allNodes.every((n) => n.data.incomeHandleSide === undefined)).toBe(true);
  });
});

describe("handleAlignNodes", () => {
  it("moves the aligned steps and leaves the others", () => {
    const { result } = setup({ nodes: [node("a", 10, 0), node("b", 200, 80), node("c", 50, 300)] });
    act(() => result.current.layout.handleAlignNodes(["a", "b"], "align-left"));
    expect(result.current.allNodes.map((n) => n.position)).toEqual([
      { x: 10, y: 0 },
      { x: 10, y: 80 },
      { x: 50, y: 300 },
    ]);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("moves a collapsed group by updating the group's position", () => {
    const { result } = setup({
      nodes: [node("m1"), node("m2"), node("free", 0, 0)],
      groups: [group("g1", ["m1", "m2"], { position: { x: 500, y: 40 } })],
    });
    act(() => result.current.layout.handleAlignNodes(["__group__g1", "free"], "align-left"));
    expect(result.current.groups[0].position.x).toBe(0);
  });

  it("does not mark the workflow dirty when the nodes are already aligned", () => {
    const { result } = setup({ nodes: [node("a", 10, 0), node("b", 10, 80)] });
    act(() => result.current.layout.handleAlignNodes(["a", "b"], "align-left"));
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("does not mark the workflow dirty when nothing can be aligned", () => {
    const { result } = setup({ nodes: [node("a", 10, 0), node("b", 200, 80)] });
    act(() => result.current.layout.handleAlignNodes(["a"], "align-left"));
    expect(markDirty).not.toHaveBeenCalled();
  });
});

describe("handleAutoLayout", () => {
  const seed = {
    nodes: [node("a", 0, 0), node("b", 0, 0), node("c", 9, 9)],
    edges: [
      edge("e1", "a", "b", { waypoints: [{ x: 1, y: 1 }], label: "keep" }),
      edge("e2", "b", "c", { waypoints: [{ x: 2, y: 2 }] }),
    ],
  };

  function layoutResult(moved: Record<string, { x: number; y: number }>) {
    return {
      nodes: Object.entries(moved).map(([id, position]) => ({ id, position })),
      movedNodeIds: Object.keys(moved),
    };
  }

  it("moves the laid-out nodes, clears bends of touched edges only, fits the view and marks dirty", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({ a: { x: 100, y: 0 }, b: { x: 300, y: 0 } }));
    const { result } = setup(seed);

    await act(async () => result.current.layout.handleAutoLayout(null, "LR" as never));

    expect(nodeById(result.current.allNodes, "a").position).toEqual({ x: 100, y: 0 });
    expect(nodeById(result.current.allNodes, "b").position).toEqual({ x: 300, y: 0 });
    expect(nodeById(result.current.allNodes, "c").position).toEqual({ x: 9, y: 9 });
    // Both edges touch a moved node here (e1: a,b - e2: b,c), so both lose their bends...
    expect(result.current.allEdges.map((e) => e.data?.waypoints)).toEqual([undefined, undefined]);
    // ...but other edge data survives.
    expect(result.current.allEdges[0].data?.label).toBe("keep");
    expect(requestFitView).toHaveBeenCalledWith(["a", "b"]);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("keeps the bends of an edge whose endpoints did not move", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({ a: { x: 100, y: 0 } }));
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c"), node("d")],
      edges: [edge("e1", "a", "b", { waypoints: [{ x: 1, y: 1 }] }), edge("e2", "c", "d", { waypoints: [{ x: 2, y: 2 }] })],
    });
    await act(async () => result.current.layout.handleAutoLayout(["a"], "LR" as never));
    expect(result.current.allEdges[0].data?.waypoints).toBeUndefined();
    expect(result.current.allEdges[1].data?.waypoints).toEqual([{ x: 2, y: 2 }]);
  });

  it("passes the selection and direction to the layout engine", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({}));
    const { result } = setup(seed);
    await act(async () => result.current.layout.handleAutoLayout(["a"], "TB" as never));
    expect(runAutoLayout).toHaveBeenCalledWith(expect.any(Array), expect.any(Array), "TB", ["a"]);
  });

  it("changes nothing when no node moved", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({}));
    const { result } = setup(seed);
    await act(async () => result.current.layout.handleAutoLayout(null, "LR" as never));
    expect(markDirty).not.toHaveBeenCalled();
    expect(requestFitView).not.toHaveBeenCalled();
    expect(result.current.layout.isAutoLayoutRunning).toBe(false);
  });

  it("reports the running state while the layout is computed", async () => {
    let finish: (value: unknown) => void = () => undefined;
    runAutoLayout.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = setup(seed);

    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.layout.handleAutoLayout(null, "LR" as never);
    });
    expect(result.current.layout.isAutoLayoutRunning).toBe(true);

    await act(async () => {
      finish(layoutResult({}));
      await pending;
    });
    expect(result.current.layout.isAutoLayoutRunning).toBe(false);
  });

  it("tells the user, moves nothing and recovers when the layout fails", async () => {
    runAutoLayout.mockRejectedValue(new Error("elk crashed"));
    const { result } = setup(seed);

    await act(async () => result.current.layout.handleAutoLayout(null, "LR" as never));

    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Auto layout failed", variant: "destructive" }),
    );
    expect(result.current.allNodes.map((n) => n.position)).toEqual(seed.nodes.map((n) => n.position));
    expect(markDirty).not.toHaveBeenCalled();
    expect(result.current.layout.isAutoLayoutRunning).toBe(false);
  });

  it("moves a collapsed group by updating the group position", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({ __group__g1: { x: 700, y: 20 } }));
    const { result } = setup({
      nodes: [node("m1"), node("m2")],
      groups: [group("g1", ["m1", "m2"])],
    });

    await act(async () => result.current.layout.handleAutoLayout(null, "LR" as never));

    expect(result.current.groups[0].position).toEqual({ x: 700, y: 20 });
    expect(result.current.allNodes.map((n) => n.position)).toEqual([{ x: 0, y: 0 }, { x: 0, y: 0 }]);
  });

  it("clears the bends of a group-boundary proxy edge when its group node moved", async () => {
    runAutoLayout.mockResolvedValue(layoutResult({ __group__g1: { x: 700, y: 20 } }));
    const { result } = setup({
      nodes: [node("src"), node("m1"), node("m2")],
      edges: [edge("e1", "src", "m1", { waypoints: [{ x: 1, y: 1 }] })],
      groups: [group("g1", ["m1", "m2"])],
    });

    await act(async () => result.current.layout.handleAutoLayout(null, "LR" as never));

    expect(result.current.allEdges[0].data?.waypoints).toBeUndefined();
  });
});

describe("referential stability", () => {
  it("returns the same handlers when nothing changed", () => {
    const { result, rerender } = setup({ nodes: [node("a")] });
    const first = result.current.layout;
    rerender();
    // `projected` is recomputed on every render in this harness, so only compare a state-free handler.
    expect(result.current.layout.handleNodeTitleChange).toBe(first.handleNodeTitleChange);
  });
});
