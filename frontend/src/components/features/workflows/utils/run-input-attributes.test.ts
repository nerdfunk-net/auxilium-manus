import { describe, expect, it } from "vitest";

import type { StaticAttributeDef } from "../types/workflow-persistence";
import {
  collectGetFromUserDeviceParams,
  mergeRunInputAttributes,
} from "./run-input-attributes";

describe("mergeRunInputAttributes", () => {
  it("adds required string attrs for get-from-user device_param names", () => {
    const nodes = [
      {
        data: {
          kind: "get-from-user",
          pluginConfig: { device_param: "target_devices" },
        },
      },
    ];
    const merged = mergeRunInputAttributes(nodes, []);
    expect(merged).toEqual([
      { name: "target_devices", type: "string", required: true },
    ] satisfies StaticAttributeDef[]);
  });

  it("preserves existing static attribute declarations", () => {
    const nodes = [
      {
        data: {
          kind: "get-from-user",
          pluginConfig: { device_param: "target_devices" },
        },
      },
    ];
    const existing: StaticAttributeDef[] = [
      { name: "target_devices", type: "string", required: false, default: "router1" },
    ];
    const merged = mergeRunInputAttributes(nodes, existing);
    expect(merged).toEqual(existing);
  });

  it("ignores get-from-user nodes without device_param", () => {
    expect(collectGetFromUserDeviceParams([{ data: { kind: "get-from-user", pluginConfig: {} } }])).toEqual(
      [],
    );
  });

  it("prunes an auto-generated attribute once its get-from-user node is deleted", () => {
    const existing: StaticAttributeDef[] = [
      { name: "target_devices", type: "string", required: true },
    ];
    const merged = mergeRunInputAttributes([], existing);
    expect(merged).toEqual([]);
  });

  it("prunes the old name and adds the new one when device_param is renamed", () => {
    const nodes = [
      {
        data: {
          kind: "get-from-user",
          pluginConfig: { device_param: "devices" },
        },
      },
    ];
    const existing: StaticAttributeDef[] = [
      { name: "target_devices", type: "string", required: true },
    ];
    const merged = mergeRunInputAttributes(nodes, existing);
    expect(merged).toEqual([{ name: "devices", type: "string", required: true }]);
  });

  it("never prunes a hand-customized attribute even when unreferenced", () => {
    const customized: StaticAttributeDef[] = [
      { name: "target_devices", type: "string", required: false, default: "router1" },
      { name: "vlan_id", type: "number", required: true },
    ];
    const merged = mergeRunInputAttributes([], customized);
    expect(merged).toEqual(customized);
  });
});
