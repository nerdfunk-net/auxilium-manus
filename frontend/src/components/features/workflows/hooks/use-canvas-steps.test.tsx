import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  BACKGROUND_Z_INDEX,
  FOREGROUND_Z_INDEX,
  STEP_GROUP_KIND,
  type CanvasGroup,
  type PersistedCanvasNode,
  type StepPayload,
  type WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import type { UseCanvasGroupsResult } from "./use-canvas-groups";
import { useCanvasSteps } from "./use-canvas-steps";
import type { UseWorkflowCanvasCoreResult } from "./use-workflow-canvas-core";

const selectNode = vi.fn();
const markDirty = vi.fn();
const appendToActiveGroup = vi.fn();
const handleAddContainerGroup = vi.fn();

beforeEach(() => {
  selectNode.mockReset();
  markDirty.mockReset();
  appendToActiveGroup.mockReset();
  handleAddContainerGroup.mockReset();
});

function step(kind: string, overrides: Record<string, unknown> = {}): StepPayload {
  return {
    kind,
    title: `Title ${kind}`,
    overview: "overview",
    description: "description",
    artifactType: "",
    requires: [],
    requiresParsed: [],
    produces: [],
    producesParsed: [],
    consumes: [],
    outcomes: [{ name: "success" }],
    ...overrides,
  } as unknown as StepPayload;
}

function node(id: string, kind = "run-command", extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "workflowNode",
    position: { x: 10, y: 20 },
    data: { kind, stepUuid: `uuid-${id}`, pluginConfig: {} },
    ...extra,
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string) {
  return { id, source, target, type: "waypoint" } as unknown as WorkflowCanvasEdge;
}

interface Seed {
  nodes?: PersistedCanvasNode[];
  edges?: WorkflowCanvasEdge[];
  groups?: CanvasGroup[];
  staticAttributes?: StaticAttributeDef[];
  projectedEdges?: unknown[];
}

const NO_PROJECTED_EDGES: unknown[] = [];

/** Real React state behind the hook's setters, like useWorkflowCanvasCore. */
function setup(seed: Seed = {}) {
  return renderHook(() => {
    const [allNodes, setAllNodes] = useState(seed.nodes ?? []);
    const [allEdges, setAllEdges] = useState(seed.edges ?? []);
    const [groups, setGroups] = useState(seed.groups ?? []);
    const [staticAttributes, setStaticAttributes] = useState(seed.staticAttributes ?? []);
    const core = {
      allNodes,
      allEdges,
      groups,
      setAllNodes,
      setAllEdges,
      setGroups,
      setStaticAttributes,
      projected: { edges: seed.projectedEdges ?? NO_PROJECTED_EDGES },
      selectNode,
      markDirty,
    } as unknown as UseWorkflowCanvasCoreResult;
    const groupsApi = {
      appendToActiveGroup,
      handleAddContainerGroup,
    } as unknown as UseCanvasGroupsResult;
    const steps = useCanvasSteps(core, groupsApi);
    return { steps, allNodes, allEdges, groups, staticAttributes };
  });
}

const nodeIds = (nodes: PersistedCanvasNode[]) => nodes.map((n) => n.id);

describe("buildStepNode", () => {
  const build = (s: StepPayload) => {
    const { result } = setup();
    return result.current.steps.buildStepNode(s, "n1", { x: 1, y: 2 });
  };

  it("builds a plain step without a pluginConfig", () => {
    const built = build(step("run-command"));
    expect(built).toMatchObject({
      id: "n1",
      type: "workflowNode",
      position: { x: 1, y: 2 },
      zIndex: FOREGROUND_Z_INDEX,
      data: { kind: "run-command", title: "Title run-command", outcomes: [{ name: "success" }] },
    });
    expect(built.data).not.toHaveProperty("pluginConfig");
    expect(built).not.toHaveProperty("width");
  });

  it("gives every node its own stepUuid", () => {
    const { result } = setup();
    const a = result.current.steps.buildStepNode(step("x"), "a", { x: 0, y: 0 });
    const b = result.current.steps.buildStepNode(step("x"), "b", { x: 0, y: 0 });
    expect(a.data.stepUuid).toBeTruthy();
    expect(a.data.stepUuid).not.toBe(b.data.stepUuid);
  });

  it.each([
    ["update-attribute", { attributes: [] }],
    ["render-jinja-template", {}],
    ["encrypt-attribute", {}],
    ["decrypt-attribute", {}],
    ["get-from-user", { device_param: "target_devices" }],
  ])("seeds default config for %s", (kind, expected) => {
    expect(build(step(kind)).data.pluginConfig).toMatchObject(expected);
  });

  it("does not share default config objects between nodes", () => {
    const { result } = setup();
    const a = result.current.steps.buildStepNode(step("get-from-user"), "a", { x: 0, y: 0 });
    (a.data.pluginConfig as Record<string, unknown>).device_param = "changed";
    const b = result.current.steps.buildStepNode(step("get-from-user"), "b", { x: 0, y: 0 });
    expect(b.data.pluginConfig).toMatchObject({ device_param: "target_devices" });
  });

  it("derives producesParsed from the default config for render-jinja-template", () => {
    const built = build(step("render-jinja-template", { producesParsed: ["ignored"] }));
    expect(built.data.producesParsed).not.toContain("ignored");
  });

  it("sizes label and background nodes from their config, background behind steps", () => {
    const label = build(step("label"));
    expect(label).toMatchObject({ type: "labelNode", zIndex: FOREGROUND_Z_INDEX, width: 200, height: 40 });
    expect(label.style).toMatchObject({ width: 200, height: 40 });

    const background = build(step("background"));
    expect(background).toMatchObject({
      type: "backgroundNode",
      zIndex: BACKGROUND_Z_INDEX,
      width: 480,
      height: 320,
    });
  });
});

describe("handleAddStep", () => {
  it("appends the node, selects it, joins the active group and marks the canvas dirty", () => {
    const { result } = setup({ nodes: [node("a-1"), node("a-2")] });

    act(() => result.current.steps.handleAddStep(step("run-command")));

    const added = result.current.allNodes[2];
    expect(added.id).toBe("run-command-3");
    expect(added.position).toEqual({ x: 160 + 3 * 44, y: 460 });
    expect(selectNode).toHaveBeenCalledWith("run-command-3");
    expect(appendToActiveGroup).toHaveBeenCalledWith("run-command-3");
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("delegates a Step Group to the group handler and adds no node", () => {
    const { result } = setup();
    act(() => result.current.steps.handleAddStep(step(STEP_GROUP_KIND)));
    expect(handleAddContainerGroup).toHaveBeenCalledWith({ x: 160 + 44, y: 460 });
    expect(result.current.allNodes).toEqual([]);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("declares the run parameter of a new Get from User step", () => {
    const { result } = setup();
    act(() => result.current.steps.handleAddStep(step("get-from-user")));
    expect(result.current.staticAttributes).toEqual([
      { name: "target_devices", type: "string", required: true },
    ]);
  });

  it("does not touch static attributes for other steps", () => {
    const { result } = setup();
    act(() => result.current.steps.handleAddStep(step("run-command")));
    expect(result.current.staticAttributes).toEqual([]);
  });

  // Ids are derived from the node count; after deleting a node that count is no
  // longer unique. Two nodes with one id corrupt the canvas (edges, selection).
  it("never reuses the id of an existing node after earlier nodes were deleted", () => {
    const { result } = setup({ nodes: [node("a-1", "a"), node("b-2", "b")] });

    act(() => result.current.steps.handleDeleteNodes(["a-1"]));
    act(() => result.current.steps.handleAddStep(step("b")));

    const ids = nodeIds(result.current.allNodes);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("handleAddStepAtPosition", () => {
  it("places the node at the drop position", () => {
    const { result } = setup({ nodes: [node("a-1")] });
    act(() => result.current.steps.handleAddStepAtPosition(step("run-command"), { x: 5, y: 6 }));
    const added = result.current.allNodes[1];
    expect(added.position).toEqual({ x: 5, y: 6 });
    expect(selectNode).toHaveBeenCalledWith(added.id);
    expect(appendToActiveGroup).toHaveBeenCalledWith(added.id);
  });

  it("creates a container group at the drop position for a Step Group", () => {
    const { result } = setup();
    act(() => result.current.steps.handleAddStepAtPosition(step(STEP_GROUP_KIND), { x: 5, y: 6 }));
    expect(handleAddContainerGroup).toHaveBeenCalledWith({ x: 5, y: 6 });
    expect(result.current.allNodes).toEqual([]);
  });

  it("never reuses the id of an existing node after earlier nodes were deleted", () => {
    const { result } = setup({ nodes: [node("a-1", "a"), node("b-2", "b")] });

    act(() => result.current.steps.handleDeleteNodes(["a-1"]));
    act(() => result.current.steps.handleAddStepAtPosition(step("b"), { x: 0, y: 0 }));

    const ids = nodeIds(result.current.allNodes);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("handleDuplicateNode", () => {
  it("copies the node offset by 32px with a new id and uuid, and selects the copy", () => {
    const { result } = setup({
      nodes: [node("run-command-1", "run-command", { selected: true })],
    });

    act(() => result.current.steps.handleDuplicateNode("run-command-1"));

    const [original, copy] = result.current.allNodes;
    expect(original.selected).toBe(false);
    expect(copy.id).toBe("run-command-2");
    expect(copy.position).toEqual({ x: 42, y: 52 });
    expect(copy.selected).toBe(true);
    expect(copy.data.stepUuid).not.toBe(original.data.stepUuid);
    expect(selectNode).toHaveBeenCalledWith("run-command-2");
    expect(markDirty).toHaveBeenCalled();
  });

  it("ignores an unknown node id", () => {
    const { result } = setup({ nodes: [node("a-1")] });
    act(() => result.current.steps.handleDuplicateNode("missing"));
    expect(result.current.allNodes).toHaveLength(1);
    expect(markDirty).not.toHaveBeenCalled();
  });

  it("never reuses the id of an existing node", () => {
    const { result } = setup({ nodes: [node("a-1", "a"), node("a-2", "a")] });

    act(() => result.current.steps.handleDeleteNodes(["a-1"]));
    // 1 node left, so the next id is a-2 - which already exists.
    act(() => result.current.steps.handleDuplicateNode("a-2"));

    const ids = nodeIds(result.current.allNodes);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("handleDeleteNodes", () => {
  it("removes the nodes and their edges and clears the selection", () => {
    const { result } = setup({
      nodes: [node("a"), node("b"), node("c")],
      edges: [edge("e1", "a", "b"), edge("e2", "b", "c")],
    });

    act(() => result.current.steps.handleDeleteNodes(["b"]));

    expect(nodeIds(result.current.allNodes)).toEqual(["a", "c"]);
    expect(result.current.allEdges).toEqual([]);
    expect(selectNode).toHaveBeenCalledWith(null);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("ungroups a group node without deleting its member steps", () => {
    const group = {
      id: "group-1",
      title: "G",
      nodeIds: ["a", "b"],
      position: { x: 0, y: 0 },
      parentGroupId: null,
    } as CanvasGroup;
    const { result } = setup({ nodes: [node("a"), node("b")], groups: [group] });

    act(() => result.current.steps.handleDeleteNodes(["__group__group-1"]));

    expect(result.current.groups).toEqual([]);
    expect(nodeIds(result.current.allNodes)).toEqual(["a", "b"]);
  });

  it("handles real nodes and groups in one call", () => {
    const group = {
      id: "group-1",
      title: "G",
      nodeIds: ["a", "b"],
      position: { x: 0, y: 0 },
      parentGroupId: null,
    } as CanvasGroup;
    const { result } = setup({ nodes: [node("a"), node("b"), node("c")], groups: [group] });

    act(() => result.current.steps.handleDeleteNodes(["c", "__group__group-1"]));

    expect(nodeIds(result.current.allNodes)).toEqual(["a", "b"]);
    expect(result.current.groups).toEqual([]);
  });
});

describe("handleDeleteEdge", () => {
  it("deletes a real edge by id", () => {
    const { result } = setup({ edges: [edge("e1", "a", "b"), edge("e2", "b", "c")] });
    act(() => result.current.steps.handleDeleteEdge("e1"));
    expect(result.current.allEdges.map((e) => e.id)).toEqual(["e2"]);
    expect(selectNode).toHaveBeenCalledWith(null);
    expect(markDirty).toHaveBeenCalled();
  });

  it("resolves a proxy edge to the real edge behind it", () => {
    const { result } = setup({
      edges: [edge("e1", "a", "b"), edge("e2", "b", "c")],
      projectedEdges: [{ id: "__group-edge__e2", data: { realEdgeId: "e2" } }],
    });
    act(() => result.current.steps.handleDeleteEdge("__group-edge__e2"));
    expect(result.current.allEdges.map((e) => e.id)).toEqual(["e1"]);
  });
});

describe("handleNodeConfigChange", () => {
  it("replaces the node's config and marks the canvas dirty", () => {
    const { result } = setup({ nodes: [node("a"), node("b")] });
    act(() => result.current.steps.handleNodeConfigChange("a", { command: "show ver" }));
    expect(result.current.allNodes[0].data.pluginConfig).toEqual({ command: "show ver" });
    expect(result.current.allNodes[1].data.pluginConfig).toEqual({});
    expect(markDirty).toHaveBeenCalledTimes(1);
  });

  it("re-derives the outcomes of a route-on-attribute step from its routes", () => {
    const { result } = setup({ nodes: [node("r", "route-on-attribute")] });
    act(() =>
      result.current.steps.handleNodeConfigChange("r", {
        routes: [{ outcome: "core", values: ["x"] }],
        default_outcome: "other",
      }),
    );
    expect(result.current.allNodes[0].data.outcomes?.map((o) => o.name)).toEqual([
      "core",
      "other",
      "failure",
    ]);
  });

  it("re-derives producesParsed of a render-jinja-template step from its output key", () => {
    const { result } = setup({ nodes: [node("t", "render-jinja-template")] });
    act(() => result.current.steps.handleNodeConfigChange("t", { output_key: "rendered_cfg" }));
    expect(result.current.allNodes[0].data.producesParsed).toEqual(["rendered_cfg"]);
  });

  it("resizes a decoration node from a numeric width/height and keeps the old size otherwise", () => {
    const label = node("l", "label", { width: 100, height: 30, style: { color: "red" } });
    const { result } = setup({ nodes: [label] });

    act(() => result.current.steps.handleNodeConfigChange("l", { width: 250 }));

    const updated = result.current.allNodes[0];
    expect(updated.width).toBe(250);
    expect(updated.height).toBe(30);
    expect(updated.style).toMatchObject({ color: "red", width: 250, height: 30 });
    expect(updated.zIndex).toBe(FOREGROUND_Z_INDEX);
  });

  it("keeps a background behind everything when it is edited", () => {
    const { result } = setup({ nodes: [node("bg", "background", { width: 1, height: 1 })] });
    act(() => result.current.steps.handleNodeConfigChange("bg", { width: 300, height: 200 }));
    expect(result.current.allNodes[0].zIndex).toBe(BACKGROUND_Z_INDEX);
  });

  it("keeps the run parameters in sync when a Get from User step changes its device_param", () => {
    const { result } = setup({
      nodes: [node("g", "get-from-user", { data: { kind: "get-from-user", pluginConfig: { device_param: "old" } } })],
      staticAttributes: [{ name: "old", type: "string", required: true }],
    });

    act(() => result.current.steps.handleNodeConfigChange("g", { device_param: "new" }));

    expect(result.current.staticAttributes).toEqual([
      { name: "new", type: "string", required: true },
    ]);
  });

  it("leaves static attributes alone when another kind of step changes", () => {
    const attrs: StaticAttributeDef[] = [{ name: "keep", type: "string", required: false }];
    const { result } = setup({ nodes: [node("a")], staticAttributes: attrs });
    act(() => result.current.steps.handleNodeConfigChange("a", { x: 1 }));
    expect(result.current.staticAttributes).toBe(attrs);
  });

  it("does not mutate the previous node", () => {
    const original = node("a");
    const snapshot = structuredClone(original);
    const { result } = setup({ nodes: [original] });
    act(() => result.current.steps.handleNodeConfigChange("a", { x: 1 }));
    expect(original).toEqual(snapshot);
  });
});

describe("handleStaticAttributesChange", () => {
  it("replaces the attributes and marks the canvas dirty", () => {
    const { result } = setup();
    const next: StaticAttributeDef[] = [{ name: "site", type: "string", required: true }];
    act(() => result.current.steps.handleStaticAttributesChange(next));
    expect(result.current.staticAttributes).toBe(next);
    expect(markDirty).toHaveBeenCalledTimes(1);
  });
});

describe("referential stability", () => {
  it("returns the same handlers when the underlying state did not change", () => {
    const { result, rerender } = setup({ nodes: [node("a")] });
    const first = result.current.steps;
    rerender();
    expect(result.current.steps).toBe(first);
  });
});
