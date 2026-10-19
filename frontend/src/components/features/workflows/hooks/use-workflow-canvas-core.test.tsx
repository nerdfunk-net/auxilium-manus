import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/lib/auth-store";

import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { useWorkflowBuilderStore } from "./use-workflow-builder-store";
import {
  useWorkflowCanvasCore,
  type LoadedCanvasState,
} from "./use-workflow-canvas-core";

// Node dragging/resizing has its own logic and tests; the core only wires it up.
const nodeChanges = vi.hoisted(() => ({ handleNodesChange: () => undefined }));
vi.mock("./use-canvas-node-changes", () => ({
  useCanvasNodeChanges: () => nodeChanges,
}));

const store = () => useWorkflowBuilderStore.getState();

beforeEach(() => {
  store().resetToNew();
  store().markSaved();
  useWorkflowBuilderStore.setState({ canvasDraft: null, selectedNodeId: null });
  useAuthStore.setState({ user: null });
});

function node(id: string, data: Record<string, unknown> = {}): PersistedCanvasNode {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: { kind: "step", title: id, ...data },
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string, extra: Record<string, unknown> = {}) {
  return { id, source, target, type: "waypoint", ...extra } as unknown as WorkflowCanvasEdge;
}

function group(id: string, nodeIds: string[]): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 0, y: 0 }, parentGroupId: null };
}

function canvas(partial: Partial<LoadedCanvasState>): LoadedCanvasState {
  return { nodes: [], edges: [], groups: [], staticAttributes: [], ...partial };
}

function setup(loaded?: LoadedCanvasState) {
  const hook = renderHook(() => useWorkflowCanvasCore());
  if (loaded) act(() => hook.result.current.applyLoadedCanvas(loaded));
  return hook;
}

const GROUP_NODE = (id: string) => `__group__${id}`;

describe("canvas state", () => {
  it("starts empty", () => {
    const { result } = setup();
    expect(result.current.allNodes).toEqual([]);
    expect(result.current.allEdges).toEqual([]);
    expect(result.current.groups).toEqual([]);
    expect(result.current.staticAttributes).toEqual([]);
  });

  it("applyLoadedCanvas replaces all four parts and clearCanvas empties them again", () => {
    const loaded = canvas({
      nodes: [node("a")],
      edges: [edge("e", "a", "a")],
      groups: [group("g", ["a", "b"])],
      staticAttributes: [{ name: "x", type: "string", required: true }],
    });
    const { result } = setup(loaded);
    expect(result.current.allNodes).toBe(loaded.nodes);
    expect(result.current.allEdges).toBe(loaded.edges);
    expect(result.current.groups).toBe(loaded.groups);
    expect(result.current.staticAttributes).toBe(loaded.staticAttributes);

    act(() => result.current.clearCanvas());
    expect(result.current.allNodes).toEqual([]);
    expect(result.current.allEdges).toEqual([]);
    expect(result.current.groups).toEqual([]);
    expect(result.current.staticAttributes).toEqual([]);
  });
});

describe("draft restore and snapshot", () => {
  const draft = (overrides: Record<string, unknown> = {}) => ({
    userId: null,
    workflowId: null,
    nodes: [node("drafted")],
    edges: [],
    groups: [],
    staticAttributes: [],
    viewport: null,
    ...overrides,
  });

  it("restores the in-progress draft of the same user and workflow", () => {
    useWorkflowBuilderStore.setState({ canvasDraft: draft() as never });
    const { result } = setup();
    expect(result.current.allNodes.map((n) => n.id)).toEqual(["drafted"]);
    expect(result.current.initialCanvasDraft).not.toBeNull();
  });

  it("ignores a draft that belongs to another user", () => {
    useAuthStore.setState({ user: { id: 5 } as never });
    useWorkflowBuilderStore.setState({ canvasDraft: draft({ userId: 9 }) as never });
    const { result } = setup();
    expect(result.current.allNodes).toEqual([]);
    expect(result.current.initialCanvasDraft).toBeNull();
  });

  it("ignores a draft of a different workflow", () => {
    useWorkflowBuilderStore.setState({ canvasDraft: draft({ workflowId: 99 }) as never });
    const { result } = setup();
    expect(result.current.allNodes).toEqual([]);
  });

  it("snapshots the latest canvas, workflow id, owner and viewport on unmount", () => {
    useAuthStore.setState({ user: { id: 5 } as never });
    useWorkflowBuilderStore.setState({ workflowId: 42 });
    const { result, unmount } = setup();
    const loaded = canvas({ nodes: [node("a"), node("b")] });
    act(() => result.current.applyLoadedCanvas(loaded));
    act(() => result.current.handleViewportChange({ x: 1, y: 2, zoom: 3 }));

    unmount();

    expect(store().canvasDraft).toMatchObject({
      workflowId: 42,
      userId: 5,
      nodes: loaded.nodes,
      viewport: { x: 1, y: 2, zoom: 3 },
    });
  });

  it("keeps the owner after a logout cleared the auth user", () => {
    useAuthStore.setState({ user: { id: 5 } as never });
    const { unmount } = setup();
    act(() => useAuthStore.setState({ user: null }));
    unmount();
    expect(store().canvasDraft?.userId).toBe(5);
  });
});

describe("opening the group of a selected step", () => {
  const loaded = canvas({
    nodes: [node("m1"), node("m2"), node("outside")],
    groups: [group("g1", ["m1", "m2"])],
  });

  it("enters the group when a member step becomes selected", () => {
    setup(loaded);
    act(() => store().selectNode("m1"));
    expect(store().activeGroupId).toBe("g1");
  });

  it("does not enter a group for a step outside any group", () => {
    setup(loaded);
    act(() => store().selectNode("outside"));
    expect(store().activeGroupId).toBeNull();
  });

  it("does not drive the user back into the group after they navigated out", () => {
    setup(loaded);
    act(() => store().selectNode("m1"));
    expect(store().activeGroupId).toBe("g1");

    act(() => store().exitToRoot());
    expect(store().activeGroupId).toBeNull();
    expect(store().selectedNodeId).toBe("m1");
  });
});

describe("handleConnect between plain steps", () => {
  const loaded = canvas({ nodes: [node("a"), node("b")] });

  it("adds a waypoint edge with the default style and marks the workflow dirty", () => {
    const { result } = setup(loaded);
    act(() => result.current.handleConnect({ source: "a", target: "b", sourceHandle: "success", targetHandle: "input" }));
    expect(result.current.allEdges).toHaveLength(1);
    expect(result.current.allEdges[0]).toMatchObject({
      source: "a",
      target: "b",
      sourceHandle: "success",
      targetHandle: "input",
      type: "waypoint",
      data: { edgeStyle: expect.any(String) },
    });
    expect(store().isDirty).toBe(true);
  });

  it("does not add the same connection twice", () => {
    const { result } = setup(loaded);
    const connection = { source: "a", target: "b", sourceHandle: "success", targetHandle: "input" };
    act(() => result.current.handleConnect(connection));
    act(() => result.current.handleConnect(connection));
    expect(result.current.allEdges).toHaveLength(1);
  });
});

describe("handleConnect with a collapsed group", () => {
  const provider = node("src", { produces: ["identity"], outcomes: [{ name: "success" }] });
  const takes = (id: string) => node(id, { requires: ["identity"] });
  const needsConfig = node("cfg", { requires: ["running_config"] });

  it("attaches to the only member step that can take the connection", () => {
    const { result } = setup(
      canvas({
        nodes: [provider, takes("m1"), needsConfig],
        groups: [group("g1", ["m1", "cfg"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: "src",
        sourceHandle: "success",
        target: GROUP_NODE("g1"),
        targetHandle: null,
      }),
    );
    expect(result.current.allEdges[0]).toMatchObject({
      source: "src",
      target: "m1",
      targetHandle: "input",
    });
    expect(result.current.pendingGroupConnection).toBeNull();
  });

  it("asks which step to use when several members can take it, then connects the chosen one", () => {
    const { result } = setup(
      canvas({
        nodes: [provider, takes("m1"), takes("m2")],
        groups: [group("g1", ["m1", "m2"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: "src",
        sourceHandle: "success",
        target: GROUP_NODE("g1"),
        targetHandle: null,
      }),
    );
    expect(result.current.allEdges).toEqual([]);
    expect(result.current.pendingGroupConnection).toMatchObject({ side: "input" });
    expect(result.current.pendingGroupConnection?.candidates.map((c) => c.nodeId).sort()).toEqual([
      "m1",
      "m2",
    ]);

    act(() =>
      result.current.resolvePendingGroupConnection(
        result.current.pendingGroupConnection!.candidates.find((c) => c.nodeId === "m2")!,
      ),
    );
    expect(result.current.allEdges[0]).toMatchObject({ source: "src", target: "m2" });
    expect(result.current.pendingGroupConnection).toBeNull();
  });

  it("drops a pending connection when the user cancels", () => {
    const { result } = setup(
      canvas({
        nodes: [provider, takes("m1"), takes("m2")],
        groups: [group("g1", ["m1", "m2"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: "src",
        sourceHandle: "success",
        target: GROUP_NODE("g1"),
        targetHandle: null,
      }),
    );
    act(() => result.current.resolvePendingGroupConnection(null));
    expect(result.current.pendingGroupConnection).toBeNull();
    expect(result.current.allEdges).toEqual([]);
  });

  it("starts from a group's output: the member's outcome becomes the source handle", () => {
    const { result } = setup(
      canvas({
        nodes: [
          node("m1", { produces: ["identity"], outcomes: [{ name: "success" }] }),
          node("m2", { outcomes: [{ name: "failure" }] }),
          takes("sink"),
        ],
        groups: [group("g1", ["m1", "m2"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: GROUP_NODE("g1"),
        sourceHandle: null,
        target: "sink",
        targetHandle: "input",
      }),
    );
    // m2 provides nothing the sink requires, so m1.success is the only candidate.
    expect(result.current.allEdges[0]).toMatchObject({
      source: "m1",
      sourceHandle: "success",
      target: "sink",
    });
  });

  it("refuses when no member step can take the connection", () => {
    const { result } = setup(
      canvas({
        nodes: [provider, needsConfig, node("plain")],
        groups: [group("g1", ["cfg", "plain"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: "src",
        sourceHandle: "success",
        target: GROUP_NODE("g1"),
        targetHandle: null,
      }),
    );
    expect(result.current.allEdges).toEqual([]);
    expect(store().lastAction).toBe("No step in this group can take this connection.");
    expect(store().workflowStatus).toBe("Error");
  });

  it("refuses to connect two groups when a choice would be needed", () => {
    const { result } = setup(
      canvas({
        nodes: [
          node("s1", { outcomes: [{ name: "a" }, { name: "b" }] }),
          node("s2"),
          takes("t1"),
          takes("t2"),
        ],
        groups: [group("gs", ["s1", "s2"]), group("gt", ["t1", "t2"])],
      }),
    );
    act(() =>
      result.current.handleConnect({
        source: GROUP_NODE("gs"),
        sourceHandle: null,
        target: GROUP_NODE("gt"),
        targetHandle: null,
      }),
    );
    expect(result.current.allEdges).toEqual([]);
    expect(store().lastAction).toBe("Open a group and connect to a step inside it.");
  });
});

describe("handleEdgesChange", () => {
  const nodes = [node("src", { produces: ["identity"] }), node("m1"), node("m2")];
  const flat = canvas({
    nodes: [node("a"), node("b"), node("c")],
    edges: [edge("e1", "a", "b"), edge("e2", "b", "c")],
  });
  const grouped = canvas({
    nodes,
    edges: [edge("e1", "src", "m1")],
    groups: [group("g1", ["m1", "m2"])],
  });

  it("removes a real edge", () => {
    const { result } = setup(flat);
    act(() => result.current.handleEdgesChange([{ type: "remove", id: "e1" }]));
    expect(result.current.allEdges.map((e) => e.id)).toEqual(["e2"]);
    expect(store().isDirty).toBe(true);
  });

  it("removes the real edge behind a proxy edge of a collapsed group", () => {
    const { result } = setup(grouped);
    const proxy = result.current.projected.edges[0];
    expect(proxy.data?.realEdgeId).toBe("e1");

    act(() => result.current.handleEdgesChange([{ type: "remove", id: proxy.id }]));

    expect(result.current.allEdges).toEqual([]);
  });

  it("carries the selection of a proxy edge to its real edge without marking the workflow dirty", () => {
    const { result } = setup(grouped);
    const proxy = result.current.projected.edges[0];
    store().markSaved();

    act(() =>
      result.current.handleEdgesChange([{ type: "select", id: proxy.id, selected: true }]),
    );

    expect(result.current.allEdges[0].selected).toBe(true);
    expect(store().isDirty).toBe(false);
  });

  it("selecting a real edge does not mark the workflow dirty", () => {
    const { result } = setup(flat);
    store().markSaved();
    act(() => result.current.handleEdgesChange([{ type: "select", id: "e1", selected: true }]));
    expect(result.current.allEdges.find((e) => e.id === "e1")?.selected).toBe(true);
    expect(store().isDirty).toBe(false);
  });
});

describe("flatProvides", () => {
  it("is computed on the flat graph, through a collapsed group", () => {
    const { result } = setup(
      canvas({
        nodes: [node("src", { produces: ["identity"] }), node("m1"), node("m2")],
        edges: [edge("e1", "src", "m1", { sourceHandle: "success" })],
        groups: [group("g1", ["m1", "m2"])],
      }),
    );
    expect(result.current.flatProvides.has("src")).toBe(false);
    expect([...result.current.flatProvides.keys()].some((key) => key.startsWith("m1"))).toBe(true);
  });
});

describe("referential stability", () => {
  it("returns the same object when nothing changed", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
