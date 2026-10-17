import { describe, expect, it } from "vitest";

import type { PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";
import { getAncestorNodeIds } from "./attribute-path-ancestors";

function step(id: string): PersistedCanvasNode {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: { kind: "run-command", title: id, description: "" },
  } as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string): WorkflowCanvasEdge {
  return { id, source, target, sourceHandle: "success", targetHandle: "input", type: "waypoint" };
}

describe("getAncestorNodeIds", () => {
  it("returns every node upstream in a linear chain", () => {
    const nodes = [step("a"), step("b"), step("c")];
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "c")];

    expect(getAncestorNodeIds("c", nodes, edges)).toEqual(new Set(["a", "b"]));
  });

  it("includes both branches of a diamond join", () => {
    const nodes = [step("a"), step("b1"), step("b2"), step("c")];
    const edges = [
      edge("e1", "a", "b1"),
      edge("e2", "a", "b2"),
      edge("e3", "b1", "c"),
      edge("e4", "b2", "c"),
    ];

    expect(getAncestorNodeIds("c", nodes, edges)).toEqual(new Set(["a", "b1", "b2"]));
  });

  it("excludes a disconnected branch", () => {
    const nodes = [step("a"), step("b"), step("unrelated")];
    const edges = [edge("e1", "a", "b")];

    expect(getAncestorNodeIds("b", nodes, edges)).toEqual(new Set(["a"]));
  });

  it("returns an empty set for a node with no ancestors", () => {
    const nodes = [step("a")];
    expect(getAncestorNodeIds("a", nodes, [])).toEqual(new Set());
  });

  it("is cycle-safe", () => {
    const nodes = [step("a"), step("b")];
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "a")];

    expect(getAncestorNodeIds("a", nodes, edges)).toEqual(new Set(["a", "b"]));
  });
});
