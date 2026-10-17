import { describe, expect, it } from "vitest";

import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { computeOutcomeProvides } from "./capability-graph";
import { listGroupConnectionCandidates } from "./group-connection-candidates";

function step(
  id: string,
  opts: {
    kind?: string;
    requires?: string[];
    produces?: string[];
    outcomes?: string[];
  } = {},
) {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: {
      kind: opts.kind ?? "update-attribute",
      title: id,
      requires: opts.requires ?? [],
      produces: opts.produces ?? [],
      outcomes: (opts.outcomes ?? ["success"]).map((name) => ({ name })),
    },
  } as unknown as PersistedCanvasNode;
}

function edge(id: string, source: string, target: string, sourceHandle = "success"): WorkflowCanvasEdge {
  return { id, source, target, sourceHandle, targetHandle: "input", type: "waypoint" };
}

function group(nodeIds: string[]): CanvasGroup {
  return { id: "g", title: "g", nodeIds, isContainer: true, position: { x: 0, y: 0 }, parentGroupId: null };
}

function run(
  side: "input" | "output",
  g: CanvasGroup,
  otherEnd: { nodeId: string; handle: string } | null,
  nodes: PersistedCanvasNode[],
  edges: WorkflowCanvasEdge[],
  groupHandleId: string | null = null,
) {
  return listGroupConnectionCandidates({
    side,
    group: g,
    groupHandleId,
    otherEnd,
    allNodes: nodes,
    allEdges: edges,
    flatProvides: computeOutcomeProvides(nodes, edges),
  });
}

describe("listGroupConnectionCandidates — group as target", () => {
  const nodes = [
    step("src", { kind: "get-from-list", produces: ["identity"] }),
    step("u1", { requires: ["identity"] }),
    step("u2", { requires: ["identity"] }),
    step("needsConfig", { requires: ["config"] }),
    step("noInput"),
  ];

  it("offers every compatible member for unconnected steps (reported scenario)", () => {
    const result = run("input", group(["u1", "u2"]), { nodeId: "src", handle: "success" }, nodes, []);
    expect(result.map((c) => c.nodeId)).toEqual(["u1", "u2"]);
    expect(result[0]).toMatchObject({ handle: "input", title: "u1" });
  });

  it("excludes members whose requirements aren't met or that take no input", () => {
    const result = run(
      "input",
      group(["u1", "needsConfig", "noInput"]),
      { nodeId: "src", handle: "success" },
      nodes,
      [],
    );
    expect(result.map((c) => c.nodeId)).toEqual(["u1"]);
  });

  it("lists entry-like members (no internal incoming edge) first", () => {
    const edges = [edge("i", "u1", "u2")];
    const result = run("input", group(["u2", "u1"]), { nodeId: "src", handle: "success" }, nodes, edges);
    expect(result.map((c) => c.nodeId)).toEqual(["u1", "u2"]);
  });

  it("resolves an existing port handle to its inner step only", () => {
    const edges = [edge("e1", "src", "u1")];
    const result = run(
      "input",
      group(["u1", "u2"]),
      { nodeId: "src", handle: "success" },
      nodes,
      edges,
      "in:e1",
    );
    expect(result.map((c) => c.nodeId)).toEqual(["u1"]);
  });

  it("returns nothing for an empty group", () => {
    expect(run("input", group([]), { nodeId: "src", handle: "success" }, nodes, [])).toEqual([]);
  });

  it("judges capabilities on the flat graph (provided through another group member's chain)", () => {
    const flat = [
      step("root", { produces: ["identity"] }),
      step("mid", { requires: ["identity"], produces: ["config"] }),
      step("tail", { requires: ["config"] }),
    ];
    const edges = [edge("a", "root", "mid")];
    const result = run("input", group(["tail", "x"]), { nodeId: "mid", handle: "success" }, flat, edges);
    expect(result.map((c) => c.nodeId)).toEqual(["tail"]);
  });
});

describe("listGroupConnectionCandidates — group as source", () => {
  const nodes = [
    step("a", { requires: ["identity"], produces: ["config"], outcomes: ["success", "failure"] }),
    step("b", { requires: ["identity"], produces: [], outcomes: ["success"] }),
    step("dest", { requires: ["config"] }),
    step("root", { produces: ["identity"] }),
  ];
  const edges = [edge("r1", "root", "a"), edge("r2", "root", "b")];

  it("offers (step, outcome) pairs whose provides satisfy the target", () => {
    const result = run("output", group(["a", "b"]), { nodeId: "dest", handle: "input" }, nodes, edges);
    expect(result.map((c) => [c.nodeId, c.handle])).toEqual([["a", "success"]]);
  });

  it("returns nothing when the target takes no input", () => {
    const n = [...nodes, step("sink")];
    expect(run("output", group(["a", "b"]), { nodeId: "sink", handle: "input" }, n, edges)).toEqual([]);
  });

  it("skips compatibility filtering when the other end is unknown (group to group)", () => {
    const result = run("output", group(["a", "b"]), null, nodes, edges);
    expect(result.map((c) => [c.nodeId, c.handle])).toEqual([
      ["a", "success"],
      ["a", "failure"],
      ["b", "success"],
    ]);
  });
});
