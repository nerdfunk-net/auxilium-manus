import { describe, expect, it } from "vitest";

import type { PersistedCanvasNode, WorkflowCanvasEdge } from "../types/workflow-canvas";
import type { StaticAttributeDef } from "../types/workflow-persistence";
import { validateCanvasWorkflow } from "./workflow-validation";

const NO_EDGES: WorkflowCanvasEdge[] = [];

function node(id: string, kind: string, title: string, pluginConfig: Record<string, unknown>) {
  return {
    id,
    type: "workflowNode",
    position: { x: 0, y: 0 },
    data: { kind, title, description: "", pluginConfig },
  } as unknown as PersistedCanvasNode;
}

describe("validateCanvasWorkflow - static attribute defaults", () => {
  it("accepts a reference/inventory attribute with an integer default", () => {
    const attrs: StaticAttributeDef[] = [
      { name: "target_inventory", type: "reference", ref_kind: "inventory", default: 1, required: false },
    ];
    const result = validateCanvasWorkflow([], NO_EDGES, [], attrs, { requireSteps: false });
    expect(result.isValid).toBe(true);
  });

  it("accepts a reference/credential attribute with a string default", () => {
    const attrs: StaticAttributeDef[] = [
      {
        name: "ssh_credential",
        type: "reference",
        ref_kind: "credential",
        default: "cisco - noc",
        required: false,
      },
    ];
    const result = validateCanvasWorkflow([], NO_EDGES, [], attrs, { requireSteps: false });
    expect(result.isValid).toBe(true);
  });

  it("rejects a reference/inventory attribute with a string default", () => {
    const attrs: StaticAttributeDef[] = [
      { name: "target_inventory", type: "reference", ref_kind: "inventory", default: "LAB", required: false },
    ];
    const result = validateCanvasWorkflow([], NO_EDGES, [], attrs, { requireSteps: false });
    expect(result.isValid).toBe(false);
    expect(result.issues[0]).toContain('default does not match type "reference"');
  });

  it("names the referencing node(s) in the error message", () => {
    const attrs: StaticAttributeDef[] = [
      { name: "target_inventory", type: "reference", ref_kind: "inventory", default: "LAB", required: false },
    ];
    const nodes = [
      node("n1", "get-nautobot-devices", "Get from Nautobot", {
        inventory_source: "run_param",
        inventory_param: "target_inventory",
      }),
    ];
    const result = validateCanvasWorkflow(nodes, NO_EDGES, [], attrs, { requireSteps: false });
    expect(result.issues[0]).toContain('used by "Get from Nautobot"');
  });

  it("omits the hint when no node references the attribute", () => {
    const attrs: StaticAttributeDef[] = [
      { name: "target_inventory", type: "reference", ref_kind: "inventory", default: "LAB", required: false },
    ];
    const result = validateCanvasWorkflow([], NO_EDGES, [], attrs, { requireSteps: false });
    expect(result.issues[0]).not.toContain("used by");
  });
});
