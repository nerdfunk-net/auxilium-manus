import { describe, expect, it } from "vitest";

import type { CanvasGroup, PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";
import {
  addNodesToGroup,
  projectCanvasView,
  removeNodesFromGroups,
  repairOrphanGroups,
} from "./canvas-group-projection";

function node(id: string, parentId?: string) {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    parentId,
    data: { kind: "log-message", title: id },
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string): WorkflowCanvasEdge {
  return { id, source, target, sourceHandle: "success", targetHandle: "input", type: "waypoint" };
}

function group(id: string, nodeIds: string[]): CanvasGroup {
  return { id, title: id, nodeIds, position: { x: 100, y: 50 }, parentGroupId: null };
}

const NODES = ["S1", "S2", "S3", "A1", "A2", "A3", "S4"].map((id) => node(id));
const EDGES = [
  edge("e1", "S1", "S2"),
  edge("e2", "S2", "S3"),
  edge("e3", "S3", "A1"),
  edge("e4", "A1", "A2"),
  edge("e5", "A2", "A3"),
  edge("e6", "A3", "S4"),
];

describe("addNodesToGroup", () => {
  it("adds a step without mutating the input groups", () => {
    const groups = [group("g", ["A1", "A2", "A3"])];
    const result = addNodesToGroup(groups, NODES, "g", ["S3"]);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.groups[0].nodeIds).toEqual(["A1", "A2", "A3", "S3"]);
    expect(groups[0].nodeIds).toEqual(["A1", "A2", "A3"]);
  });

  it("moves a step between groups and dissolves a group left with < 2 members", () => {
    const groups = [group("g1", ["S1", "S2"]), group("g2", ["A1", "A2"])];
    const result = addNodesToGroup(groups, NODES, "g2", ["S2"]);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.groups.map((g) => g.id)).toEqual(["g2"]);
      expect(result.groups[0].nodeIds).toEqual(["A1", "A2", "S2"]);
    }
  });

  it("rejects unknown groups and background children", () => {
    expect(addNodesToGroup([], NODES, "nope", ["S3"]).ok).toBe(false);
    const nodes = [node("A1"), node("A2"), node("X", "bg")];
    const bad = addNodesToGroup([group("g", ["A1", "A2"])], nodes, "g", ["X"]);
    expect(bad.ok).toBe(false);
  });
});

describe("removeNodesFromGroups", () => {
  it("removes a member, keeping the group when ≥ 2 remain", () => {
    const result = removeNodesFromGroups([group("g", ["A1", "A2", "A3"])], ["A3"]);
    expect(result[0].nodeIds).toEqual(["A1", "A2"]);
  });

  it("dissolves the group when fewer than two members remain", () => {
    expect(removeNodesFromGroups([group("g", ["A1", "A2"])], ["A2"])).toEqual([]);
  });
});

describe("projection after moving S3 into the group", () => {
  it("turns S2->S3 into the group's input port and keeps the S4 output", () => {
    const grouped = [group("g", ["S3", "A1", "A2", "A3"])];
    const { nodes, edges } = projectCanvasView(NODES, EDGES, grouped, null);
    expect(nodes.map((n) => n.id).sort()).toEqual(["S1", "S2", "S4", "__group__g"]);
    const proxy = edges.find((e) => e.target === "__group__g");
    expect(proxy?.targetHandle).toBe("in:e2");
    expect(edges.find((e) => e.source === "__group__g")?.sourceHandle).toBe("out:e6");
    expect(edges.some((e) => e.id === "__group-edge__e3")).toBe(false);
  });
});

describe("container groups (palette Step Group)", () => {
  const container: CanvasGroup = { ...group("c", []), isContainer: true };

  it("survives at zero members and is never dissolved by removal", () => {
    expect(removeNodesFromGroups([{ ...container, nodeIds: ["A1", "A2"] }], ["A1", "A2"])).toEqual([
      { ...container, nodeIds: [] },
    ]);
    expect(repairOrphanGroups(NODES, [container])).toEqual([container]);
  });

  it("accepts steps into an empty container and projects it with no ports", () => {
    const result = addNodesToGroup([container], NODES, "c", ["S3"]);
    expect(result.ok).toBe(true);
    const { nodes } = projectCanvasView(NODES, [], [container], null);
    const node = nodes.find((n) => n.id === "__group__c");
    expect(node?.data).toMatchObject({ memberCount: 0, inputPorts: [], outputPorts: [] });
  });
});
