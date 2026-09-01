import { describe, expect, it } from "vitest";

import type { Capability } from "@/lib/capability-types";

import type {
  ProjectedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { computeOutcomeProvides, getOutcomeProvides } from "./capability-graph";

function step(
  id: string,
  overrides: Partial<ProjectedCanvasNode["data"]> = {},
): ProjectedCanvasNode {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: {
      kind: "run-command",
      title: id,
      description: "",
      requires: [],
      produces: [],
      consumes: [],
      outcomes: [{ name: "success" }],
      ...overrides,
    },
  } as ProjectedCanvasNode;
}

function edge(
  id: string,
  source: string,
  target: string,
  sourceHandle = "success",
): WorkflowCanvasEdge {
  return {
    id,
    source,
    target,
    sourceHandle,
    targetHandle: "input",
    type: "waypoint",
  };
}

function caps(
  provides: ReturnType<typeof getOutcomeProvides>,
): Capability[] {
  return [...provides.capabilities].sort();
}

describe("computeOutcomeProvides — failure-class outcomes", () => {
  const selector = step("sel", {
    kind: "get-nautobot-devices",
    requires: [],
    produces: ["identity"],
    outcomes: [{ name: "success" }],
  });
  const getConfigs = step("cfg", {
    kind: "get-device-configs",
    requires: ["identity"],
    produces: ["running_config", "startup_config"],
    outcomes: [{ name: "success" }, { name: "failure" }],
  });
  const edges = [edge("e1", "sel", "cfg")];

  it("success outcome carries input + produced capabilities", () => {
    const map = computeOutcomeProvides([selector, getConfigs], edges);
    expect(caps(getOutcomeProvides(map, "cfg", "success"))).toEqual([
      "identity",
      "running_config",
      "startup_config",
    ]);
  });

  it("failure outcome carries only the input capabilities", () => {
    const map = computeOutcomeProvides([selector, getConfigs], edges);
    expect(caps(getOutcomeProvides(map, "cfg", "failure"))).toEqual(["identity"]);
  });

  it("failure outcome still carries capabilities added by upstream steps", () => {
    const attrs = step("attr", {
      kind: "get-nautobot-attributes",
      requires: ["identity"],
      produces: ["attributes"],
      outcomes: [{ name: "success" }],
    });
    const map = computeOutcomeProvides(
      [selector, attrs, getConfigs],
      [edge("e1", "sel", "attr"), edge("e2", "attr", "cfg")],
    );
    expect(caps(getOutcomeProvides(map, "cfg", "failure"))).toEqual([
      "attributes",
      "identity",
    ]);
  });

  it("mismatch is not treated as failure-class and keeps produced output", () => {
    const compare = step("cmp", {
      kind: "compare-data",
      requires: ["identity"],
      produces: ["parsed"],
      producesParsed: ["comparison_diff"],
      outcomes: [{ name: "match" }, { name: "mismatch" }, { name: "failure" }],
    });
    const map = computeOutcomeProvides(
      [selector, compare],
      [edge("e1", "sel", "cmp")],
    );
    expect(caps(getOutcomeProvides(map, "cmp", "mismatch"))).toEqual([
      "identity",
      "parsed",
    ]);
    expect(
      getOutcomeProvides(map, "cmp", "mismatch").parsedKeys,
    ).toEqual(["comparison_diff"]);
    // failure on the same step drops both the produced capability and key.
    expect(caps(getOutcomeProvides(map, "cmp", "failure"))).toEqual(["identity"]);
    expect(getOutcomeProvides(map, "cmp", "failure").parsedKeys).toEqual([]);
  });

  it("failure outcome is the exact input state — produces skipped, consumes not applied", () => {
    const consumer = step("cons", {
      kind: "config-to-attributes",
      requires: ["identity", "parsed"],
      produces: ["attributes"],
      consumes: ["parsed"],
      outcomes: [{ name: "success" }, { name: "failure" }],
    });
    const producer = step("prod", {
      kind: "parse-cisco-config",
      requires: ["identity"],
      produces: ["parsed"],
      outcomes: [{ name: "success" }],
    });
    const map = computeOutcomeProvides(
      [selector, producer, consumer],
      [edge("e1", "sel", "prod"), edge("e2", "prod", "cons")],
    );
    // A failed device is returned untouched by the executor (model_copy keeps
    // its capabilities), so the failure branch mirrors the input state exactly:
    // `parsed` is still there (consume never happened) and `attributes` was
    // never added. The success branch, by contrast, drops `parsed`.
    expect(caps(getOutcomeProvides(map, "cons", "failure"))).toEqual([
      "identity",
      "parsed",
    ]);
    expect(caps(getOutcomeProvides(map, "cons", "success"))).toEqual([
      "attributes",
      "identity",
    ]);
  });
});
