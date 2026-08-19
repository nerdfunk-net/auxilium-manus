import { describe, expect, it } from "vitest";

import type {
  BackgroundCanvasNode,
  FunnelCanvasNode,
  GroupCanvasNode,
  LabelCanvasNode,
  WorkflowCanvasEdge,
  WorkflowCanvasNode,
} from "../types/workflow-canvas";
import { applyElkLayout, buildElkGraph } from "./auto-layout";

function step(
  id: string,
  overrides: Partial<WorkflowCanvasNode["data"]> = {},
  position = { x: 0, y: 0 },
): WorkflowCanvasNode {
  return {
    id,
    type: "workflowNode",
    position,
    width: 320,
    height: 128,
    measured: { width: 320, height: 128 },
    data: {
      kind: "run-command",
      title: id,
      description: "",
      outcomes: [{ name: "success" }],
      ...overrides,
    },
  };
}

function funnel(
  id: string,
  overrides: Partial<FunnelCanvasNode["data"]> = {},
  position = { x: 0, y: 0 },
): FunnelCanvasNode {
  return {
    id,
    type: "funnelNode",
    position,
    width: 40,
    height: 40,
    measured: { width: 40, height: 40 },
    data: {
      kind: "funnel",
      title: id,
      description: "",
      ...overrides,
    },
  };
}

function background(id: string, position = { x: 0, y: 0 }): BackgroundCanvasNode {
  return {
    id,
    type: "backgroundNode",
    position,
    width: 480,
    height: 320,
    data: { kind: "background", title: id, description: "" },
  };
}

function label(id: string, position = { x: 0, y: 0 }): LabelCanvasNode {
  return {
    id,
    type: "labelNode",
    position,
    data: { kind: "label", title: id, description: "" },
  };
}

function group(id: string, position = { x: 0, y: 0 }): GroupCanvasNode {
  return {
    id,
    type: "groupNode",
    position,
    width: 320,
    height: 128,
    measured: { width: 320, height: 128 },
    data: { kind: "__canvas-group__", title: id, memberCount: 2, groupId: id },
  };
}

function edge(
  id: string,
  source: string,
  target: string,
  sourceHandle: string | undefined = "success",
  targetHandle: string | undefined = "input",
): WorkflowCanvasEdge {
  return { id, source, target, sourceHandle, targetHandle, type: "waypoint" };
}

describe("buildElkGraph", () => {
  it("excludes label/background decorations from the graph entirely", () => {
    const a = step("a");
    const b = step("b", { requires: ["identity"] });
    const nodes = [a, b, label("l1"), background("bg1")];
    const edges = [edge("e1", "a", "b")];

    const { graph, movableNodeIds } = buildElkGraph(nodes, edges, {
      direction: "horizontal",
      selectedNodeIds: null,
    });

    expect(graph.children?.map((c) => c.id).sort()).toEqual(["a", "b"]);
    expect(movableNodeIds).toEqual(new Set(["a", "b"]));
  });

  it("gives a funnel exactly input/output ports regardless of stale outcomes/requires data", () => {
    const f = funnel("f1", {
      // Stale leftover from before this node became a funnel.
      outcomes: [{ name: "success" }, { name: "failure" }],
      requires: ["identity"],
    });
    const { graph } = buildElkGraph([f], [], { direction: "horizontal", selectedNodeIds: null });

    const node = graph.children?.find((c) => c.id === "f1");
    expect(node?.ports?.map((p) => p.id)).toEqual(["f1__input", "f1__output"]);
  });

  it("omits the workflowNode target port when requires is empty, keeps one source port per outcome", () => {
    const a = step("a", { requires: [], outcomes: [{ name: "success" }, { name: "failure" }] });
    const { graph } = buildElkGraph([a], [], { direction: "horizontal", selectedNodeIds: null });

    const node = graph.children?.find((c) => c.id === "a");
    expect(node?.ports?.map((p) => p.id)).toEqual(["a__success", "a__failure"]);
    expect(node?.layoutOptions?.["elk.portConstraints"]).toBe("FIXED_ORDER");
  });

  it("gives the group node a target port only when its entry step requires something", () => {
    const withoutRequires = group("g1");
    const { graph: g1 } = buildElkGraph([withoutRequires], [], {
      direction: "horizontal",
      selectedNodeIds: null,
    });
    expect(g1.children?.[0].ports?.map((p) => p.id)).toEqual(["g1__success"]);

    const withRequires: GroupCanvasNode = {
      ...group("g2"),
      data: {
        ...withoutRequires.data,
        groupId: "g2",
        requires: ["identity"],
      },
    };
    const { graph: g2 } = buildElkGraph([withRequires], [], {
      direction: "horizontal",
      selectedNodeIds: null,
    });
    expect(g2.children?.[0].ports?.map((p) => p.id)).toEqual(["g2__input", "g2__success"]);
  });

  it("maps direction to ELK's RIGHT/DOWN", () => {
    const { graph: horizontal } = buildElkGraph([step("a")], [], {
      direction: "horizontal",
      selectedNodeIds: null,
    });
    const { graph: vertical } = buildElkGraph([step("a")], [], {
      direction: "vertical",
      selectedNodeIds: null,
    });
    expect(horizontal.layoutOptions?.["elk.direction"]).toBe("RIGHT");
    expect(vertical.layoutOptions?.["elk.direction"]).toBe("DOWN");
  });

  it("pins unselected neighbors of a selection as fixed-position anchors, excluded from movableNodeIds", () => {
    const a = step("a", {}, { x: 0, y: 0 });
    const b = step("b", { requires: ["identity"] }, { x: 400, y: 0 });
    const c = step(
      "c",
      { requires: ["identity"] },
      { x: 800, y: 0 },
    );
    const nodes = [a, b, c];
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "c")];

    const { graph, movableNodeIds } = buildElkGraph(nodes, edges, {
      direction: "horizontal",
      selectedNodeIds: ["b"],
    });

    expect(movableNodeIds).toEqual(new Set(["b"]));
    const ids = graph.children?.map((c) => c.id).sort();
    expect(ids).toEqual(["a", "b", "c"]);

    const pinnedA = graph.children?.find((c) => c.id === "a");
    const pinnedC = graph.children?.find((c) => c.id === "c");
    expect(pinnedA).toMatchObject({ x: 0, y: 0 });
    expect(pinnedC).toMatchObject({ x: 800, y: 0 });
    expect(graph.layoutOptions?.["elk.interactiveLayout"]).toBe("true");
  });

  it("drops edges between two pinned (unselected) neighbors", () => {
    const a = step("a", {}, { x: 0, y: 0 });
    const b = step("b", { requires: ["identity"] }, { x: 400, y: 0 });
    const c = step(
      "c",
      { requires: ["identity"] },
      { x: 800, y: 0 },
    );
    const selected = step(
      "sel",
      { requires: ["identity"] },
      { x: 1200, y: 0 },
    );
    // a -> b -> c is entirely outside the selection except b -> sel.
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "c"), edge("e3", "b", "sel")];

    const { graph } = buildElkGraph([a, b, c, selected], edges, {
      direction: "horizontal",
      selectedNodeIds: ["sel"],
    });

    expect(graph.edges?.map((e) => e.id).sort()).toEqual(["e3"]);
  });
});

describe("applyElkLayout", () => {
  it("writes back positions only for movable nodes, leaving others untouched", () => {
    const a = step("a", {}, { x: 0, y: 0 });
    const b = step("b", {}, { x: 999, y: 999 });
    const nodes = [a, b];
    const movableNodeIds = new Set(["a"]);
    const elkResult = {
      id: "__root__",
      children: [
        { id: "a", x: 111, y: 222 },
        { id: "b", x: 500, y: 500 },
      ],
    };

    const result = applyElkLayout(nodes, elkResult, movableNodeIds);
    expect(result.find((n) => n.id === "a")?.position).toEqual({ x: 111, y: 222 });
    expect(result.find((n) => n.id === "b")?.position).toEqual({ x: 999, y: 999 });
  });

  it("converts an ELK absolute position back to parent-relative for a background-parented node", () => {
    const bg = background("bg1", { x: 100, y: 100 });
    const child: WorkflowCanvasNode = { ...step("child"), parentId: "bg1", position: { x: 5, y: 5 } };
    const nodes = [bg, child];
    const movableNodeIds = new Set(["child"]);
    // ELK saw the child at its absolute position (150, 150).
    const elkResult = { id: "__root__", children: [{ id: "child", x: 150, y: 150 }] };

    const result = applyElkLayout(nodes, elkResult, movableNodeIds);
    expect(result.find((n) => n.id === "child")?.position).toEqual({ x: 50, y: 50 });
  });
});
