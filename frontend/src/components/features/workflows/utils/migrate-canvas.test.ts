import { describe, expect, it } from "vitest";

import type { PluginDefinition } from "../types/plugin-registry";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import { migrateCanvasState } from "./migrate-canvas";

// Fixtures are deliberately loose: persisted canvases from older versions do
// not satisfy today's types, which is exactly what the migration handles.
function node(overrides: Record<string, unknown> = {}): PersistedCanvasNode {
  const { data, ...rest } = overrides;
  return {
    id: "n1",
    type: "workflowNode",
    position: { x: 0, y: 0 },
    zIndex: 1,
    data: { kind: "custom-step", overview: "ov", ...(data as object) },
    ...rest,
  } as unknown as PersistedCanvasNode;
}

function edge(overrides: Record<string, unknown> = {}): WorkflowCanvasEdge {
  return {
    id: "e1",
    source: "n1",
    target: "n2",
    type: "waypoint",
    ...overrides,
  } as unknown as WorkflowCanvasEdge;
}

function plugin(overrides: Partial<PluginDefinition> = {}): PluginDefinition {
  return {
    id: "custom-step",
    name: "Custom",
    overview: "plugin overview",
    description: "",
    artifact_type: "",
    directory: "custom_step",
    enabled: true,
    requires: [],
    produces: [],
    consumes: [],
    requires_parsed: [],
    produces_parsed: [],
    outcomes: [],
    metadata: { configuration_input: [] },
    ...overrides,
  };
}

describe("migrateCanvasState", () => {
  it("returns the same objects and migrated=false for an up-to-date canvas", () => {
    const nodes = [node()];
    const edges = [edge()];
    const result = migrateCanvasState(nodes, edges, []);
    expect(result.migrated).toBe(false);
    expect(result.nodes[0]).toBe(nodes[0]);
    expect(result.edges[0]).toBe(edges[0]);
  });

  it("is idempotent: migrating a migrated canvas changes nothing", () => {
    const legacy = [
      node({
        zIndex: undefined,
        data: { mandatoryInputs: [{ name: "a" }], portOrientation: "vertical" },
      }),
      node({ id: "lbl", type: "workflowNode", data: { kind: "label" } }),
      node({ id: "gfu", data: { kind: "get-from-user" } }),
    ];
    const legacyEdges = [edge({ data: { edgeStyle: "smooth" } })];
    const first = migrateCanvasState(legacy, legacyEdges, [plugin()]);
    expect(first.migrated).toBe(true);

    const second = migrateCanvasState(first.nodes, first.edges, [plugin()]);
    expect(second.migrated).toBe(false);
    expect(second.nodes).toEqual(first.nodes);
    expect(second.edges).toEqual(first.edges);
  });

  it("does not mutate its input", () => {
    const input = node({ data: { portOrientation: "vertical" } });
    const snapshot = JSON.parse(JSON.stringify(input));
    migrateCanvasState([input], [], []);
    expect(JSON.parse(JSON.stringify(input))).toEqual(snapshot);
  });

  describe("legacy IO fields", () => {
    it("drops mandatoryInputs", () => {
      const [migrated] = migrateCanvasState(
        [node({ data: { mandatoryInputs: [{ name: "x" }] } })],
        [],
        [],
      ).nodes;
      expect(migrated.data).not.toHaveProperty("mandatoryInputs");
    });

    it("maps vertical portOrientation to top/bottom handles", () => {
      const [migrated] = migrateCanvasState(
        [node({ data: { portOrientation: "vertical" } })],
        [],
        [],
      ).nodes;
      expect(migrated.data).toMatchObject({
        incomeHandleSide: "top",
        outcomeHandleSide: "bottom",
      });
      expect(migrated.data).not.toHaveProperty("portOrientation");
    });

    it("maps horizontal portOrientation to left/right handles", () => {
      const [migrated] = migrateCanvasState(
        [node({ data: { portOrientation: "horizontal" } })],
        [],
        [],
      ).nodes;
      expect(migrated.data).toMatchObject({
        incomeHandleSide: "left",
        outcomeHandleSide: "right",
      });
    });

    it("keeps explicit handle sides when portOrientation is also present", () => {
      const [migrated] = migrateCanvasState(
        [
          node({
            data: {
              portOrientation: "vertical",
              incomeHandleSide: "right",
              outcomeHandleSide: "left",
            },
          }),
        ],
        [],
        [],
      ).nodes;
      expect(migrated.data).toMatchObject({
        incomeHandleSide: "right",
        outcomeHandleSide: "left",
      });
    });
  });

  describe("plugin defaults", () => {
    it("fills missing capability fields from the plugin", () => {
      const p = plugin({
        requires: ["device.list"],
        produces: ["config.text"],
        consumes: ["inventory"],
        requires_parsed: ["parsed.a"],
        produces_parsed: ["parsed.b"],
        outcomes: [{ name: "ok" }, { name: "failed" }],
        artifact_type: "report",
      });
      const result = migrateCanvasState(
        [node({ data: { overview: undefined } })],
        [],
        [p],
      );
      expect(result.migrated).toBe(true);
      expect(result.nodes[0].data).toMatchObject({
        requires: ["device.list"],
        produces: ["config.text"],
        consumes: ["inventory"],
        requiresParsed: ["parsed.a"],
        producesParsed: ["parsed.b"],
        outcomes: [{ name: "ok" }, { name: "failed" }],
        artifactType: "report",
        overview: "plugin overview",
      });
    });

    it("never overwrites values the node already has", () => {
      const p = plugin({
        requires: ["from.plugin"],
        outcomes: [{ name: "plugin-outcome" }],
        artifact_type: "plugin-artifact",
      });
      const own = node({
        data: {
          requires: ["own.capability"],
          outcomes: [{ name: "mine" }],
          artifactType: "mine",
          overview: "my overview",
        },
      });
      const result = migrateCanvasState([own], [], [p]);
      expect(result.migrated).toBe(false);
      expect(result.nodes[0]).toBe(own);
    });

    it("ignores nodes whose kind has no plugin", () => {
      const result = migrateCanvasState(
        [node({ data: { kind: "unknown", overview: undefined } })],
        [],
        [plugin()],
      );
      expect(result.migrated).toBe(false);
    });
  });

  describe("node type and stacking", () => {
    it.each([
      ["label", "labelNode"],
      ["background", "backgroundNode"],
      ["custom-step", "workflowNode"],
    ])("corrects the React Flow type for kind %s", (kind, type) => {
      const [migrated] = migrateCanvasState(
        [node({ type: "wrongNode", data: { kind } })],
        [],
        [],
      ).nodes;
      expect(migrated.type).toBe(type);
    });

    it("puts background nodes behind and steps in front", () => {
      const nodes = migrateCanvasState(
        [
          node({ id: "bg", type: "backgroundNode", zIndex: 1, data: { kind: "background" } }),
          node({ id: "step", zIndex: undefined }),
        ],
        [],
        [],
      ).nodes;
      expect(nodes.find((n) => n.id === "bg")?.zIndex).toBe(-1);
      expect(nodes.find((n) => n.id === "step")?.zIndex).toBe(1);
    });

    it("leaves zIndex undefined for a node nested in a background", () => {
      const [migrated] = migrateCanvasState(
        [node({ parentId: "bg", zIndex: 1 })],
        [],
        [],
      ).nodes;
      expect(migrated.zIndex).toBeUndefined();
    });
  });

  describe("label and background nodes", () => {
    it("adds default config and size to a label without pluginConfig", () => {
      const [migrated] = migrateCanvasState(
        [node({ type: "labelNode", data: { kind: "label" } })],
        [],
        [],
      ).nodes;
      expect(migrated.data.pluginConfig).toMatchObject({ text: "Label", width: 200, height: 40 });
      expect(migrated.width).toBe(200);
      expect(migrated.height).toBe(40);
      expect(migrated.style).toMatchObject({ width: 200, height: 40 });
    });

    it("keeps a custom numeric size", () => {
      const [migrated] = migrateCanvasState(
        [
          node({
            type: "backgroundNode",
            zIndex: -1,
            width: 100,
            height: 50,
            data: { kind: "background", pluginConfig: { width: 100, height: 50 } },
          }),
        ],
        [],
        [],
      ).nodes;
      expect(migrated.width).toBe(100);
      expect(migrated.height).toBe(50);
    });

    it("falls back to the default size when the configured size is not a number", () => {
      const [migrated] = migrateCanvasState(
        [
          node({
            type: "backgroundNode",
            zIndex: -1,
            data: { kind: "background", pluginConfig: { width: "wide", height: null } },
          }),
        ],
        [],
        [],
      ).nodes;
      expect(migrated.width).toBe(480);
      expect(migrated.height).toBe(320);
    });
  });

  describe("get-from-user", () => {
    it.each([[undefined], [{}]])(
      "fills the default device_param when pluginConfig is %j",
      (pluginConfig) => {
        const [migrated] = migrateCanvasState(
          [node({ data: { kind: "get-from-user", pluginConfig } })],
          [],
          [],
        ).nodes;
        expect(migrated.data.pluginConfig).toMatchObject({ device_param: "target_devices" });
      },
    );

    it.each([[""], ["   "]])(
      "replaces a blank device_param (%j) with the default",
      (blank) => {
        const [migrated] = migrateCanvasState(
          [node({ data: { kind: "get-from-user", pluginConfig: { device_param: blank } } })],
          [],
          [],
        ).nodes;
        expect(migrated.data.pluginConfig).toMatchObject({ device_param: "target_devices" });
      },
    );

    it("keeps a configured device_param", () => {
      const own = node({
        data: { kind: "get-from-user", pluginConfig: { device_param: "my_devices" } },
      });
      const result = migrateCanvasState([own], [], []);
      expect(result.migrated).toBe(false);
      expect(result.nodes[0]).toBe(own);
    });
  });

  describe("edges", () => {
    it("renames the legacy smooth edge style to bezier", () => {
      const result = migrateCanvasState([], [edge({ data: { edgeStyle: "smooth" } })], []);
      expect(result.migrated).toBe(true);
      expect(result.edges[0].data).toMatchObject({ edgeStyle: "bezier" });
    });

    it("rewrites the target handle to 'input' when the target declares requires", () => {
      const target = node({ id: "n2", data: { requires: ["device.list"] } });
      const result = migrateCanvasState(
        [target],
        [edge({ targetHandle: "legacy-handle-3" })],
        [],
      );
      expect(result.edges[0].targetHandle).toBe("input");
    });

    it("leaves the target handle alone when the target has no requires", () => {
      const target = node({ id: "n2" });
      const e = edge({ targetHandle: "legacy-handle-3" });
      const result = migrateCanvasState([target], [e], []);
      expect(result.edges[0]).toBe(e);
      expect(result.migrated).toBe(false);
    });

    it("uses requires filled in by the plugin migration for the same pass", () => {
      const target = node({ id: "n2", data: { overview: undefined } });
      const result = migrateCanvasState(
        [target],
        [edge({ targetHandle: "old" })],
        [plugin({ requires: ["device.list"] })],
      );
      expect(result.edges[0].targetHandle).toBe("input");
    });
  });
});
