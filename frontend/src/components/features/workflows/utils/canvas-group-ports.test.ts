import { describe, expect, it } from "vitest";

import type { WorkflowCanvasEdge } from "../types/workflow-canvas";
import { deriveGroupPorts } from "./canvas-group-ports";

function edge(
  id: string,
  source: string,
  target: string,
  sourceHandle = "success",
  targetHandle = "input",
): WorkflowCanvasEdge {
  return { id, source, target, sourceHandle, targetHandle, type: "waypoint" };
}

describe("deriveGroupPorts", () => {
  const edges = [
    edge("e1", "S1", "S2"),
    edge("e2", "S2", "S3"),
    edge("e3", "S3", "A1"),
    edge("e4", "A1", "A2"),
    edge("e5", "A2", "A3"),
    edge("e6", "A3", "S4"),
  ];

  it("derives one input and one output port for a chain group", () => {
    const ports = deriveGroupPorts(["A1", "A2", "A3"], edges);
    expect(ports.inputs).toEqual([
      { edgeId: "e3", innerNodeId: "A1", innerHandle: "input", outerNodeId: "S3" },
    ]);
    expect(ports.outputs).toEqual([
      { edgeId: "e6", innerNodeId: "A3", innerHandle: "success", outerNodeId: "S4" },
    ]);
  });

  it("moving S3 in turns S2->S3 into the input port and S3->A1 internal", () => {
    const ports = deriveGroupPorts(["S3", "A1", "A2", "A3"], edges);
    expect(ports.inputs.map((p) => [p.edgeId, p.innerNodeId])).toEqual([["e2", "S3"]]);
    expect(ports.outputs.map((p) => p.edgeId)).toEqual(["e6"]);
  });

  it("supports multiple outputs (branching) and fan-in", () => {
    const branching = [
      edge("a", "X", "B1"),
      edge("b", "Y", "B1"),
      edge("c", "B1", "Z1", "success"),
      edge("d", "B1", "Z2", "failure"),
    ];
    const ports = deriveGroupPorts(["B1", "B2"], branching);
    expect(ports.inputs.map((p) => p.edgeId)).toEqual(["a", "b"]);
    expect(ports.outputs.map((p) => [p.edgeId, p.innerHandle])).toEqual([
      ["c", "success"],
      ["d", "failure"],
    ]);
  });

  it("ignores purely internal edges and unrelated edges", () => {
    const ports = deriveGroupPorts(["A1", "A2"], [edge("i", "A1", "A2"), edge("u", "P", "Q")]);
    expect(ports).toEqual({ inputs: [], outputs: [] });
  });
});
