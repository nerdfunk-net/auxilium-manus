import { renderHook } from "@testing-library/react";
import type { NodeChange } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BACKGROUND_Z_INDEX,
  FOREGROUND_Z_INDEX,
  type CanvasGroup,
  type PersistedCanvasNode,
  type ProjectedCanvasNode,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { groupNodeId } from "../utils/canvas-group-projection";
import { useCanvasNodeChanges } from "./use-canvas-node-changes";
import type { UseCanvasNodeChangesOptions } from "./use-canvas-node-changes";

const setAllNodes = vi.fn();
const setAllEdges = vi.fn();
const setGroups = vi.fn();
const markDirty = vi.fn();

function step(id: string, x = 0, y = 0, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "workflowNode",
    position: { x, y },
    data: { kind: "get-config", pluginConfig: {} },
    width: 100,
    height: 50,
    ...extra,
  } as unknown as PersistedCanvasNode;
}

function background(id: string, x: number, y: number, w: number, h: number) {
  return {
    id,
    type: "backgroundNode",
    position: { x, y },
    width: w,
    height: h,
    data: { kind: "background", pluginConfig: { color: "blue" } },
  } as unknown as PersistedCanvasNode;
}

function label(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "labelNode",
    position: { x: 0, y: 0 },
    data: { kind: "label", pluginConfig: { text: "hi" } },
    ...extra,
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string) {
  return { id, source, target } as WorkflowCanvasEdge;
}

function group(id: string, nodeIds: string[], extra: Partial<CanvasGroup> = {}): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 10, y: 10 }, parentGroupId: null, ...extra };
}

function groupNode(g: CanvasGroup, extra: Record<string, unknown> = {}) {
  return {
    id: groupNodeId(g.id),
    type: "groupNode",
    position: g.position,
    width: 320,
    height: 128,
    data: { kind: "__canvas-group__", title: g.title },
    ...extra,
  } as unknown as ProjectedCanvasNode;
}

interface Seed {
  nodes?: PersistedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  groups?: CanvasGroup[];
  projected?: ProjectedCanvasNode[];
}

function setup(seed: Seed = {}) {
  const nodes = seed.nodes ?? [];
  const groups = seed.groups ?? [];
  const options: UseCanvasNodeChangesOptions = {
    allNodes: nodes,
    setAllNodes,
    allEdges: seed.edges ?? [],
    setAllEdges,
    groups,
    setGroups,
    projectedNodes: seed.projected ?? ([...nodes, ...groups.map((g) => groupNode(g))] as ProjectedCanvasNode[]),
    markDirty,
  };
  const { result } = renderHook(() => useCanvasNodeChanges(options));
  const apply = (...changes: NodeChange<ProjectedCanvasNode>[]) => result.current.handleNodesChange(changes);
  return { apply, options, result };
}

const lastNodes = () => setAllNodes.mock.lastCall?.[0] as PersistedCanvasNode[];
const lastGroups = () => setGroups.mock.lastCall?.[0] as CanvasGroup[];
const move = (id: string, x: number, y: number, dragging?: boolean): NodeChange<ProjectedCanvasNode> =>
  ({ type: "position", id, position: { x, y }, dragging }) as NodeChange<ProjectedCanvasNode>;

beforeEach(() => {
  for (const spy of [setAllNodes, setAllEdges, setGroups, markDirty]) spy.mockReset();
});

describe("moving steps", () => {
  it("writes the new position, puts the step in front and marks the canvas dirty", () => {
    const { apply } = setup({ nodes: [step("a"), step("b")] });
    apply(move("a", 40, 60, true));
    const next = lastNodes();
    expect(next.find((n) => n.id === "a")).toMatchObject({
      position: { x: 40, y: 60 },
      zIndex: FOREGROUND_Z_INDEX,
    });
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("leaves every other node untouched (same object)", () => {
    const a = step("a");
    const b = step("b", 5, 5);
    const { apply } = setup({ nodes: [a, b] });
    apply(move("a", 1, 1, true));
    expect(lastNodes()[1]).toBe(b);
  });

  it("does not write anything back for a change that touches nothing", () => {
    const { apply } = setup({ nodes: [step("a")] });
    apply({ type: "position", id: "ghost", position: { x: 1, y: 1 }, dragging: true } as NodeChange<ProjectedCanvasNode>);
    expect(setAllNodes).not.toHaveBeenCalled();
    expect(setAllEdges).not.toHaveBeenCalled();
    expect(setGroups).not.toHaveBeenCalled();
  });

  it("does not mutate the nodes it was given", () => {
    const nodes = [step("a")];
    const snapshot = JSON.stringify(nodes);
    const { apply } = setup({ nodes });
    apply(move("a", 9, 9, false));
    expect(JSON.stringify(nodes)).toBe(snapshot);
  });
});

describe("background containment on drag end", () => {
  const bg = background("bg", 100, 100, 400, 300);

  it("a step dropped onto a background becomes its child with a relative position", () => {
    const { apply } = setup({ nodes: [bg, step("a")] });
    apply(move("a", 200, 200, false));
    expect(lastNodes().find((n) => n.id === "a")).toMatchObject({
      parentId: "bg",
      position: { x: 100, y: 100 },
    });
  });

  it("does not re-evaluate containment while the drag is still going", () => {
    const { apply } = setup({ nodes: [bg, step("a")] });
    apply(move("a", 200, 200, true));
    expect(lastNodes().find((n) => n.id === "a")?.parentId).toBeUndefined();
  });

  it("a child dragged off its background returns to absolute coordinates", () => {
    const child = step("a", 10, 10, { parentId: "bg" });
    const { apply } = setup({ nodes: [bg, child] });
    apply(move("a", 900, 900, false));
    const moved = lastNodes().find((n) => n.id === "a");
    expect(moved?.parentId).toBeUndefined();
    expect(moved?.position).toEqual({ x: 1000, y: 1000 });
    expect(moved?.zIndex).toBe(FOREGROUND_Z_INDEX);
  });

  it("a child that stays inside keeps no foreground z-index", () => {
    const child = step("a", 10, 10, { parentId: "bg" });
    const { apply } = setup({ nodes: [bg, child] });
    apply(move("a", 50, 50, false));
    const moved = lastNodes().find((n) => n.id === "a");
    expect(moved?.parentId).toBe("bg");
    expect(moved?.zIndex).toBeUndefined();
  });
});

describe("resizing", () => {
  it("rounds a background's size into node and plugin config and pins it behind", () => {
    const bg = background("bg", 0, 0, 100, 100);
    const { apply } = setup({ nodes: [bg] });
    apply({ type: "dimensions", id: "bg", resizing: true, dimensions: { width: 321.6, height: 200.2 }, setAttributes: true } as NodeChange<ProjectedCanvasNode>);
    const next = lastNodes().find((n) => n.id === "bg") as unknown as {
      width: number;
      height: number;
      zIndex: number;
      data: { pluginConfig: Record<string, unknown> };
    };
    expect(next.width).toBe(322);
    expect(next.height).toBe(200);
    expect(next.zIndex).toBe(BACKGROUND_Z_INDEX);
    expect(next.data.pluginConfig).toEqual({ color: "blue", width: 322, height: 200 });
    expect(markDirty).toHaveBeenCalled();
  });

  it("a label stores its resized size in its plugin config", () => {
    const { apply } = setup({ nodes: [label("l", { width: 80, height: 30 })] });
    apply({ type: "dimensions", id: "l", resizing: false, dimensions: { width: 150.4, height: 40.6 }, setAttributes: true } as NodeChange<ProjectedCanvasNode>);
    const next = lastNodes().find((n) => n.id === "l") as unknown as {
      width: number;
      data: { pluginConfig: Record<string, unknown> };
    };
    expect(next.width).toBe(150);
    expect(next.data.pluginConfig).toEqual({ text: "hi", width: 150, height: 41 });
  });

  it("a passive first-mount measurement does not mark the canvas dirty", () => {
    const { apply } = setup({ nodes: [step("a")] });
    apply({ type: "dimensions", id: "a", dimensions: { width: 200, height: 80 } } as NodeChange<ProjectedCanvasNode>);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("an unmeasured background keeps its config size instead of writing zeros", () => {
    const bg = { ...background("bg", 0, 0, 100, 100), width: undefined, height: undefined } as unknown as PersistedCanvasNode;
    const { apply } = setup({ nodes: [bg] });
    apply({ type: "select", id: "bg", selected: true });
    const next = lastNodes().find((n) => n.id === "bg") as unknown as { data: { pluginConfig: Record<string, unknown> } };
    expect(next.data.pluginConfig).toEqual({ color: "blue" });
  });
});

describe("selection", () => {
  it("selecting a step is UI-only: it is stored but never marks the canvas dirty", () => {
    const { apply } = setup({ nodes: [step("a")] });
    apply({ type: "select", id: "a", selected: true });
    expect(lastNodes().find((n) => n.id === "a")?.selected).toBe(true);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("a mixed batch with a real change does mark it dirty", () => {
    const { apply } = setup({ nodes: [step("a"), step("b")] });
    apply({ type: "select", id: "a", selected: true }, move("b", 3, 3, true));
    expect(markDirty).toHaveBeenCalledTimes(1);
  });
});

describe("removing steps", () => {
  it("drops the step and the edges that touch it", () => {
    const { apply } = setup({
      nodes: [step("a"), step("b"), step("c")],
      edges: [edge("e1", "a", "b"), edge("e2", "b", "c"), edge("e3", "a", "c")],
    });
    apply({ type: "remove", id: "b" });
    expect(lastNodes().map((n) => n.id)).toEqual(["a", "c"]);
    expect((setAllEdges.mock.lastCall?.[0] as WorkflowCanvasEdge[]).map((e) => e.id)).toEqual(["e3"]);
    expect(markDirty).toHaveBeenCalled();
  });

  it("removes the step from its group and dissolves a group left with one member", () => {
    const { apply } = setup({
      nodes: [step("a"), step("b"), step("c")],
      groups: [group("g1", ["a", "b"]), group("g2", ["a", "b", "c"])],
    });
    apply({ type: "remove", id: "a" });
    expect(lastGroups().map((g) => [g.id, g.nodeIds])).toEqual([["g2", ["b", "c"]]]);
  });

  it("keeps an emptied container group", () => {
    const { apply } = setup({
      nodes: [step("a")],
      groups: [group("g1", ["a"], { isContainer: true })],
    });
    apply({ type: "remove", id: "a" });
    expect(lastGroups().map((g) => [g.id, g.nodeIds])).toEqual([["g1", []]]);
  });

  it("deleting a background keeps its children at their absolute position", () => {
    const { apply } = setup({
      nodes: [background("bg", 100, 100, 400, 300), step("a", 10, 20, { parentId: "bg" })],
    });
    apply({ type: "remove", id: "bg" });
    const child = lastNodes().find((n) => n.id === "a");
    expect(lastNodes().map((n) => n.id)).toEqual(["a"]);
    expect(child?.parentId).toBeUndefined();
    expect(child?.position).toEqual({ x: 110, y: 120 });
  });

  it("removing several steps in one batch removes them all", () => {
    const { apply } = setup({ nodes: [step("a"), step("b"), step("c")] });
    apply({ type: "remove", id: "a" }, { type: "remove", id: "c" });
    expect(lastNodes().map((n) => n.id)).toEqual(["b"]);
  });
});

describe("group nodes", () => {
  const g = group("g1", ["a", "b"]);
  const seed = () => ({ nodes: [step("a"), step("b")], groups: [g] });

  it("deleting the Group node dissolves the group and keeps its steps", () => {
    const { apply } = setup(seed());
    apply({ type: "remove", id: groupNodeId("g1") });
    expect(lastGroups()).toEqual([]);
    expect(setAllNodes).not.toHaveBeenCalled();
    expect(markDirty).toHaveBeenCalled();
  });

  it("moving the Group node persists its position on the CanvasGroup", () => {
    const { apply } = setup(seed());
    apply(move(groupNodeId("g1"), 300, 400, true));
    expect(lastGroups()[0]).toMatchObject({ id: "g1", position: { x: 300, y: 400 } });
    expect(setAllNodes).not.toHaveBeenCalled();
  });

  it("selecting the Group node round-trips through the CanvasGroup, without dirtying", () => {
    const { apply } = setup(seed());
    apply({ type: "select", id: groupNodeId("g1"), selected: true });
    expect(lastGroups()[0]?.selected).toBe(true);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("re-selecting an already-selected group does not rewrite the groups", () => {
    const selected = group("g1", ["a", "b"], { selected: true });
    const { apply } = setup({ nodes: [step("a"), step("b")], groups: [selected] });
    apply({ type: "select", id: groupNodeId("g1"), selected: true });
    expect(setGroups).not.toHaveBeenCalled();
  });

  it("dropping the Group node onto a background attaches it with a relative position", () => {
    const bg = background("bg", 100, 100, 600, 400);
    const { apply } = setup({
      nodes: [bg, step("a"), step("b")],
      groups: [g],
    });
    apply(move(groupNodeId("g1"), 200, 200, false));
    expect(lastGroups()[0]).toMatchObject({ parentId: "bg", position: { x: 100, y: 100 } });
  });

  it("an unknown Group node id is ignored", () => {
    const { apply } = setup({ nodes: [step("a")], projected: [groupNode(g)] });
    apply(move(groupNodeId("ghost"), 1, 1, true));
    expect(setGroups).not.toHaveBeenCalled();
  });
});

describe("useCanvasNodeChanges stability", () => {
  it("returns the same object when nothing changed", () => {
    const options: UseCanvasNodeChangesOptions = {
      allNodes: [],
      setAllNodes,
      allEdges: [],
      setAllEdges,
      groups: [],
      setGroups,
      projectedNodes: [],
      markDirty,
    };
    const { result, rerender } = renderHook(() => useCanvasNodeChanges(options));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
