import { describe, expect, it } from "vitest";

import type { ConditionGroup, ConditionItem, ConditionTree } from "../types/device-selector";
import { ALL_DEVICES_OR_MESSAGE, findAllDevicesConflict } from "./all-devices-conflicts";

const cond = (field: string, value = "x", operator = "equals"): ConditionItem => ({
  id: `${field}-${value}`,
  field,
  operator,
  value,
});
const all = (): ConditionItem => cond("all_devices", "true");
const group = (
  logic: ConditionGroup["logic"],
  internalLogic: ConditionGroup["internalLogic"],
  ...items: ConditionGroup["items"]
): ConditionGroup => ({ id: `g-${logic}-${internalLogic}`, type: "group", logic, internalLogic, items });
const tree = (internalLogic: "AND" | "OR", ...items: ConditionTree["items"]): ConditionTree => ({
  type: "root",
  internalLogic,
  items,
});

describe("findAllDevicesConflict", () => {
  it("accepts All Devices under AND with other conditions", () => {
    expect(findAllDevicesConflict(tree("AND", all(), cond("location", "City A", "not_equals")))).toBeNull();
  });

  it("accepts All Devices alone, under either connector", () => {
    expect(findAllDevicesConflict(tree("AND", all()))).toBeNull();
    expect(findAllDevicesConflict(tree("OR", all()))).toBeNull();
  });

  it("flags the one-click AND -> OR toggle on All Devices plus a condition", () => {
    expect(findAllDevicesConflict(tree("OR", all(), cond("location", "City A", "not_equals")))).toBe(
      ALL_DEVICES_OR_MESSAGE,
    );
  });

  it("flags All Devices beside a normal group under OR", () => {
    expect(findAllDevicesConflict(tree("OR", all(), group("AND", "AND", cond("role"))))).toBe(
      ALL_DEVICES_OR_MESSAGE,
    );
  });

  it("allows a NOT group beside All Devices under OR: it is subtracted, not ORed", () => {
    expect(findAllDevicesConflict(tree("OR", all(), group("NOT", "AND", cond("name"))))).toBeNull();
  });

  it("flags an OR group that holds All Devices and another condition", () => {
    expect(findAllDevicesConflict(tree("AND", group("AND", "OR", all(), cond("role"))))).toBe(
      ALL_DEVICES_OR_MESSAGE,
    );
  });

  it("finds the conflict in a nested group", () => {
    const nested = group("AND", "AND", group("AND", "OR", all(), cond("role")));
    expect(findAllDevicesConflict(tree("AND", cond("status"), nested))).toBe(ALL_DEVICES_OR_MESSAGE);
  });

  it("does not treat a NOT group's inner OR as an OR of its own", () => {
    expect(findAllDevicesConflict(tree("AND", group("NOT", "OR", all(), cond("role"))))).toBeNull();
  });

  it("ignores ORs that have no All Devices", () => {
    expect(findAllDevicesConflict(tree("OR", cond("role", "a"), cond("role", "b")))).toBeNull();
  });
});
