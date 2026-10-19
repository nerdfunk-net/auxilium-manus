import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CanvasGroup, PersistedCanvasNode } from "../types/workflow-canvas";
import { useCanvasGroups } from "./use-canvas-groups";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

const selectNode = vi.fn();
const markDirty = vi.fn();
const markError = vi.fn();
const enterGroup = vi.fn();
const exitToRoot = vi.fn();

vi.mock("./use-workflow-builder-store", () => ({
  useWorkflowBuilderStore: (selector: (state: { exitToRoot: () => void }) => unknown) =>
    selector({ exitToRoot }),
}));

beforeEach(() => {
  for (const spy of [selectNode, markDirty, markError, enterGroup, exitToRoot]) spy.mockReset();
});

function node(id: string, x = 0, y = 0, extra: Record<string, unknown> = {}) {
  return { id, type: "workflowNode", position: { x, y }, data: { kind: "k" }, ...extra } as unknown as PersistedCanvasNode;
}

function group(id: string, nodeIds: string[], extra: Partial<CanvasGroup> = {}): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 100, y: 200 }, parentGroupId: null, ...extra };
}

interface Seed {
  nodes?: PersistedCanvasNode[];
  groups?: CanvasGroup[];
  activeGroupId?: string | null;
}

function setup(seed: Seed = {}) {
  return renderHook(() => {
    const [allNodes, setAllNodes] = useState(seed.nodes ?? []);
    const [groups, setGroups] = useState(seed.groups ?? []);
    const core = {
      allNodes,
      setAllNodes,
      groups,
      setGroups,
      activeGroupId: seed.activeGroupId ?? null,
      selectNode,
      markDirty,
      markError,
      enterGroup,
    } as unknown as UseWorkflowCanvasCoreResult;
    return { api: useCanvasGroups(core), allNodes, groups };
  });
}

const positionOf = (nodes: PersistedCanvasNode[], id: string) =>
  nodes.find((n) => n.id === id)?.position;

describe("appendToActiveGroup", () => {
  it("does nothing at the root", () => {
    const groups = [group("g1", ["a", "b"])];
    const { result } = setup({ groups });
    act(() => result.current.api.appendToActiveGroup("c"));
    expect(result.current.groups).toBe(groups);
  });

  it("adds the node to the active group only", () => {
    const { result } = setup({
      groups: [group("g1", ["a", "b"]), group("g2", ["x", "y"])],
      activeGroupId: "g1",
    });
    act(() => result.current.api.appendToActiveGroup("c"));
    expect(result.current.groups.map((g) => g.nodeIds)).toEqual([["a", "b", "c"], ["x", "y"]]);
  });
});

describe("handleMoveToGroup", () => {
  it("moves the steps into the group, clears the selection and marks dirty", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c")],
      groups: [group("g1", ["a", "b"])],
    });
    act(() => result.current.api.handleMoveToGroup(["c"], "g1"));
    expect(result.current.groups[0].nodeIds).toEqual(["a", "b", "c"]);
    expect(selectNode).toHaveBeenCalledWith(null);
    expect(markDirty).toHaveBeenCalledTimes(1);
    expect(markError).not.toHaveBeenCalled();
  });

  it("reports the reason and changes nothing when the target group is gone", () => {
    const groups = [group("g1", ["a", "b"])];
    const { result } = setup({ nodes: [node("a"), node("b"), node("c")], groups });
    act(() => result.current.api.handleMoveToGroup(["c"], "missing"));
    expect(markError).toHaveBeenCalledWith("The target group no longer exists.");
    expect(result.current.groups).toBe(groups);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("refuses steps that sit inside a background", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c", 0, 0, { parentId: "bg" })],
      groups: [group("g1", ["a", "b"])],
    });
    act(() => result.current.api.handleMoveToGroup(["c"], "g1"));
    expect(markError).toHaveBeenCalledWith(expect.stringContaining("background"));
    expect(result.current.groups[0].nodeIds).toEqual(["a", "b"]);
  });

  it("takes a step out of its previous group and dissolves that group when it gets too small", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("x"), node("y")],
      groups: [group("g1", ["a", "b"]), group("g2", ["x", "y"])],
    });
    act(() => result.current.api.handleMoveToGroup(["x"], "g1"));
    expect(result.current.groups.map((g) => [g.id, g.nodeIds])).toEqual([["g1", ["a", "b", "x"]]]);
  });
});

describe("handleMoveOutOfGroup", () => {
  const nodes = [node("a", 5, 5), node("b", 6, 6), node("c", 7, 7)];

  it("parks the steps to the right of the group node, stacked one below the other", () => {
    const { result } = setup({
      nodes,
      groups: [group("g1", ["a", "b", "c"], { position: { x: 100, y: 200 } })],
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a", "b"]));
    expect(positionOf(result.current.allNodes, "a")).toEqual({ x: 460, y: 200 });
    expect(positionOf(result.current.allNodes, "b")).toEqual({ x: 460, y: 340 });
    expect(positionOf(result.current.allNodes, "c")).toEqual({ x: 7, y: 7 });
    // One member left, so the group is dissolved.
    expect(result.current.groups).toEqual([]);
  });

  it("keeps a group that still has two members", () => {
    const { result } = setup({
      nodes: [...nodes, node("d")],
      groups: [group("g1", ["a", "b", "c", "d"])],
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(result.current.groups[0].nodeIds).toEqual(["b", "c", "d"]);
    expect(exitToRoot).not.toHaveBeenCalled();
  });

  it("dissolves a group left with fewer than two members, but keeps its remaining step", () => {
    const { result } = setup({ nodes, groups: [group("g1", ["a", "b"])] });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(result.current.groups).toEqual([]);
    expect(result.current.allNodes.map((n) => n.id)).toEqual(["a", "b", "c"]);
  });

  it("uses the group's absolute position when the group is attached to a background", () => {
    const { result } = setup({
      nodes: [node("bg", 1000, 500), node("a"), node("b"), node("c")],
      groups: [group("g1", ["a", "b", "c"], { position: { x: 10, y: 20 }, parentId: "bg" })],
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(positionOf(result.current.allNodes, "a")).toEqual({ x: 1010 + 360, y: 520 });
  });

  it("handles steps from several groups, each relative to its own group", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c"), node("x"), node("y"), node("z")],
      groups: [
        group("g1", ["a", "b", "c"], { position: { x: 0, y: 0 } }),
        group("g2", ["x", "y", "z"], { position: { x: 1000, y: 1000 } }),
      ],
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a", "x"]));
    expect(positionOf(result.current.allNodes, "a")).toEqual({ x: 360, y: 0 });
    expect(positionOf(result.current.allNodes, "x")).toEqual({ x: 1360, y: 1000 });
  });

  it("leaves the opened group and returns to the root when it was dissolved", () => {
    const { result } = setup({
      nodes,
      groups: [group("g1", ["a", "b"])],
      activeGroupId: "g1",
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(exitToRoot).toHaveBeenCalledTimes(1);
  });

  it("stays in the opened group when it survives", () => {
    const { result } = setup({
      nodes: [...nodes, node("d")],
      groups: [group("g1", ["a", "b", "c", "d"])],
      activeGroupId: "g1",
    });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(exitToRoot).not.toHaveBeenCalled();
  });

  it("clears the selection and marks dirty", () => {
    const { result } = setup({ nodes, groups: [group("g1", ["a", "b", "c"])] });
    act(() => result.current.api.handleMoveOutOfGroup(["a"]));
    expect(selectNode).toHaveBeenCalledWith(null);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });
});

describe("handleGroupSelectedSteps", () => {
  it.each([[["a"]], [[]]])("needs at least two steps (%j)", (ids) => {
    const { result } = setup({ nodes: [node("a")] });
    act(() => result.current.api.handleGroupSelectedSteps(ids));
    expect(markError).toHaveBeenCalledWith("Select at least two steps to create a group.");
    expect(result.current.groups).toEqual([]);
  });

  it("refuses steps that already belong to a group", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c")],
      groups: [group("g1", ["a", "b"])],
    });
    act(() => result.current.api.handleGroupSelectedSteps(["b", "c"]));
    expect(markError).toHaveBeenCalledWith(expect.stringContaining("already belong"));
    expect(result.current.groups).toHaveLength(1);
  });

  it("creates a group at the average position of its members and selects it", () => {
    const { result } = setup({ nodes: [node("a", 0, 0), node("b", 100, 50), node("c", 999, 999)] });
    act(() => result.current.api.handleGroupSelectedSteps(["a", "b"]));

    const [created] = result.current.groups;
    expect(created).toMatchObject({
      title: "New group",
      nodeIds: ["a", "b"],
      position: { x: 50, y: 25 },
      parentGroupId: null,
    });
    expect(created.isContainer).toBeUndefined();
    expect(created.id).toMatch(/^group-/);
    expect(selectNode).toHaveBeenCalledWith(`__group__${created.id}`);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("gives every group its own id", () => {
    const { result } = setup({ nodes: [node("a"), node("b"), node("c"), node("d")] });
    act(() => result.current.api.handleGroupSelectedSteps(["a", "b"]));
    act(() => result.current.api.handleGroupSelectedSteps(["c", "d"]));
    const [first, second] = result.current.groups;
    expect(first.id).not.toBe(second.id);
  });
});

describe("handleAddContainerGroup", () => {
  it("creates an empty container group at the position and selects it", () => {
    const { result } = setup();
    act(() => result.current.api.handleAddContainerGroup({ x: 7, y: 8 }));
    const [created] = result.current.groups;
    expect(created).toMatchObject({ nodeIds: [], isContainer: true, position: { x: 7, y: 8 } });
    expect(selectNode).toHaveBeenCalledWith(`__group__${created.id}`);
    expect(markDirty).toHaveBeenCalled();
  });

  it("refuses to nest a group inside an opened group", () => {
    const { result } = setup({ groups: [group("g1", ["a", "b"])], activeGroupId: "g1" });
    act(() => result.current.api.handleAddContainerGroup({ x: 0, y: 0 }));
    expect(markError).toHaveBeenCalledWith(expect.stringContaining("nested"));
    expect(result.current.groups).toHaveLength(1);
    expect(markDirty).not.toHaveBeenCalled();
  });
});

describe("rename / ungroup / open", () => {
  it("renames only the given group", () => {
    const { result } = setup({ groups: [group("g1", ["a", "b"]), group("g2", ["x", "y"])] });
    act(() => result.current.api.handleRenameGroup("g2", "Core"));
    expect(result.current.groups.map((g) => g.title)).toEqual(["g1", "Core"]);
    expect(markDirty).toHaveBeenCalled();
  });

  it("ungroups without touching the member steps", () => {
    const { result } = setup({
      nodes: [node("a"), node("b")],
      groups: [group("g1", ["a", "b"])],
    });
    act(() => result.current.api.handleUngroupGroup("g1"));
    expect(result.current.groups).toEqual([]);
    expect(result.current.allNodes).toHaveLength(2);
    expect(selectNode).toHaveBeenCalledWith(null);
  });

  it("opens a group through the core", () => {
    const { result } = setup({ groups: [group("g1", ["a", "b"])] });
    act(() => result.current.api.handleOpenGroup("g1"));
    expect(enterGroup).toHaveBeenCalledWith("g1");
  });
});

describe("referential stability", () => {
  it("returns the same handlers when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current.api;
    rerender();
    expect(result.current.api).toBe(first);
  });
});
