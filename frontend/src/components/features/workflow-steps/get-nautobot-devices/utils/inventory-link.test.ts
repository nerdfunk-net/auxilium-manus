import { describe, expect, it } from "vitest";

import { emptyTree } from "../condition-builder/types";
import type { SavedInventory } from "../types/saved-inventory";
import { inventoryLinkPatch, previewRequestFor } from "./inventory-link";

function inventory(overrides: Partial<SavedInventory> = {}): SavedInventory {
  return {
    id: 42,
    name: "LAB",
    description: null,
    conditions: [
      {
        version: 2,
        tree: {
          type: "root",
          internalLogic: "OR",
          items: [{ id: "a", field: "name", operator: "equals", value: "LAB" }],
        },
      },
    ],
    inventory_type: "filter",
    device_ids: null,
    template_category: null,
    template_name: null,
    scope: "global",
    group_path: null,
    created_by: "admin",
    is_active: true,
    created_at: null,
    updated_at: null,
    ...overrides,
  } as SavedInventory;
}

describe("inventoryLinkPatch", () => {
  it("links the step to the saved inventory without copying its filter", () => {
    const patch = inventoryLinkPatch(inventory());

    expect(patch).toEqual({
      inventory_id: 42,
      inventory_name: "LAB",
      inventory_type: "filter",
      device_filter: emptyTree(),
      device_ids: [],
    });
  });

  it("does not copy a static inventory's device list either", () => {
    const patch = inventoryLinkPatch(
      inventory({ inventory_type: "static", device_ids: ["a", "b"], conditions: [] }),
    );

    expect(patch.inventory_type).toBe("static");
    expect(patch.device_ids).toEqual([]);
    expect(patch.device_filter).toEqual(emptyTree());
    expect(patch.inventory_id).toBe(42);
  });

  it("replaces a stale copy left in the step config when merged over it", () => {
    const stale = {
      nautobot_source_id: "src",
      inventory_id: 2,
      device_filter: { id: "root", logic: "OR", negate: false, items: [{ id: "x" }] },
      device_ids: ["old"],
      fan_out: { enabled: true },
    };

    const merged = { ...stale, ...inventoryLinkPatch(inventory()) };

    expect(merged.inventory_id).toBe(42);
    expect(merged.device_filter).toEqual(emptyTree());
    expect(merged.device_ids).toEqual([]);
    expect(merged.nautobot_source_id).toBe("src");
    expect(merged.fan_out).toEqual({ enabled: true });
  });
});

describe("previewRequestFor", () => {
  const base = {
    source_id: "lab 1",
    inventory_type: "filter" as const,
    device_filter: emptyTree(),
    device_ids: [] as string[],
  };

  it("previews a linked inventory by id, exactly as a run resolves it", () => {
    const request = previewRequestFor({ ...base, inventory_id: 42 });

    expect(request).toEqual({
      method: "GET",
      path: "sources/nautobot/42/devices?source_id=lab%201",
    });
  });

  it("ignores a stale copy when an inventory is linked", () => {
    const request = previewRequestFor({
      ...base,
      inventory_id: 42,
      inventory_type: "static",
      device_ids: ["old"],
    });

    expect(request.method).toBe("GET");
  });

  it("previews an ad-hoc static list through the device-id endpoint", () => {
    const request = previewRequestFor({
      ...base,
      inventory_id: null,
      inventory_type: "static",
      device_ids: ["a"],
    });

    expect(request).toEqual({
      method: "POST",
      path: "sources/nautobot/preview-device-ids",
      body: { source_id: "lab 1", device_ids: ["a"] },
    });
  });

  it("previews an ad-hoc filter through the operations endpoint", () => {
    const tree = {
      id: "root",
      logic: "AND" as const,
      negate: false,
      items: [{ id: "c", field: "role", operator: "equals", value: "leaf" }],
    };

    const request = previewRequestFor({ ...base, inventory_id: null, device_filter: tree });

    expect(request).toEqual({
      method: "POST",
      path: "sources/nautobot/preview",
      body: {
        source_id: "lab 1",
        operations: [
          {
            operation_type: "AND",
            conditions: [{ field: "role", operator: "equals", value: "leaf" }],
            nested_operations: [],
          },
        ],
      },
    });
  });
});
