import { describe, expect, it } from "vitest";

import { parseProposedConditionTree } from "./parse-condition-tree";

const condition = { id: "1", field: "role", operator: "equals", value: "Network" };
const group = {
  id: "2",
  type: "group",
  logic: "NOT",
  internalLogic: "OR",
  items: [{ id: "3", field: "tag", operator: "equals", value: "lab" }],
};

describe("parseProposedConditionTree", () => {
  it("accepts a root with conditions and a group", () => {
    const tree = { type: "root", internalLogic: "AND", items: [condition, group] };

    expect(parseProposedConditionTree(tree)).toEqual(tree);
  });

  it("returns a clean copy without unknown keys", () => {
    const parsed = parseProposedConditionTree({
      type: "root",
      internalLogic: "OR",
      extra: "x",
      items: [{ ...condition, junk: 1 }],
    });

    expect(parsed).toEqual({ type: "root", internalLogic: "OR", items: [condition] });
  });

  it.each([
    ["null", null],
    ["a string", "tree"],
    ["no items", { type: "root", internalLogic: "AND" }],
    ["items not an array", { type: "root", internalLogic: "AND", items: "x" }],
    ["wrong type", { type: "group", internalLogic: "AND", items: [] }],
    ["bad root logic", { type: "root", internalLogic: "XOR", items: [] }],
    ["a condition without a value", { type: "root", internalLogic: "AND", items: [{ ...condition, value: 5 }] }],
    ["a null item", { type: "root", internalLogic: "AND", items: [null] }],
    ["a group with bad logic", { type: "root", internalLogic: "AND", items: [{ ...group, logic: "OR" }] }],
    ["a group item that is not a condition", { type: "root", internalLogic: "AND", items: [{ ...group, items: [group] }] }],
    ["a group without items", { type: "root", internalLogic: "AND", items: [{ ...group, items: undefined }] }],
    ["too many items", { type: "root", internalLogic: "AND", items: Array.from({ length: 101 }, () => condition) }],
  ])("rejects %s", (_name, value) => {
    expect(parseProposedConditionTree(value)).toBeNull();
  });

  it("rejects a deeply nested tree instead of recursing", () => {
    let nested: unknown = condition;
    for (let i = 0; i < 5000; i += 1) {
      nested = { id: String(i), type: "group", logic: "AND", internalLogic: "AND", items: [nested] };
    }

    expect(parseProposedConditionTree({ type: "root", internalLogic: "AND", items: [nested] })).toBeNull();
  });
});
