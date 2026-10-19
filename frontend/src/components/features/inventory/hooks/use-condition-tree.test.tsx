import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  ConditionGroup,
  ConditionItem,
  ConditionTree,
} from "../types/device-selector";
import { createEmptyTree, generateId, useConditionTree } from "./use-condition-tree";

const cond = (id: string): ConditionItem => ({ id, field: "name", operator: "eq", value: id });
const group = (
  id: string,
  items: (ConditionItem | ConditionGroup)[] = [],
): ConditionGroup => ({ id, type: "group", logic: "AND", internalLogic: "AND", items });

/** root -> [c1, g1 -> [c2, g2 -> [c3]]] */
function nestedTree(): ConditionTree {
  return {
    ...createEmptyTree(),
    items: [cond("c1"), group("g1", [cond("c2"), group("g2", [cond("c3")])])],
  };
}

function setup(tree?: ConditionTree) {
  const hook = renderHook(() => useConditionTree());
  if (tree) {
    act(() => hook.result.current.setConditionTree(tree));
  }
  return hook;
}

const ids = (items: (ConditionItem | ConditionGroup)[]) => items.map((item) => item.id);
const groupById = (tree: ConditionTree, id: string) =>
  (tree.items.find((item) => item.id === id) ?? null) as ConditionGroup | null;

describe("createEmptyTree / generateId", () => {
  it("returns a fresh empty root each time", () => {
    const a = createEmptyTree();
    const b = createEmptyTree();
    expect(a).toEqual({ type: "root", internalLogic: "AND", items: [] });
    expect(a).not.toBe(b);
    expect(a.items).not.toBe(b.items);
  });

  it("generates distinct ids", () => {
    const generated = new Set(Array.from({ length: 500 }, generateId));
    expect(generated.size).toBe(500);
  });
});

describe("flatConditionsToTree", () => {
  it("returns an empty tree for no conditions", () => {
    const { result } = setup();
    expect(result.current.flatConditionsToTree([])).toEqual(createEmptyTree());
    expect(
      result.current.flatConditionsToTree(undefined as unknown as []),
    ).toEqual(createEmptyTree());
  });

  it("maps each condition to an item with its own id", () => {
    const { result } = setup();
    const tree = result.current.flatConditionsToTree([
      { field: "a", operator: "eq", value: "1" },
      { field: "b", operator: "ne", value: "2" },
    ] as never);
    expect(tree.items).toMatchObject([
      { field: "a", operator: "eq", value: "1" },
      { field: "b", operator: "ne", value: "2" },
    ]);
    expect(new Set(ids(tree.items)).size).toBe(2);
    expect(tree.internalLogic).toBe("AND");
  });

  it("takes the root logic from the first condition only", () => {
    const { result } = setup();
    const tree = result.current.flatConditionsToTree([
      { field: "a", operator: "eq", value: "1", logic: "OR" },
      { field: "b", operator: "eq", value: "2", logic: "AND" },
    ] as never);
    expect(tree.internalLogic).toBe("OR");
  });
});

describe("addConditionToTree", () => {
  it("adds to the root when no group is targeted", () => {
    const { result } = setup();
    act(() => result.current.addConditionToTree("name", "eq", "r1"));
    expect(result.current.conditionTree.items).toMatchObject([
      { field: "name", operator: "eq", value: "r1" },
    ]);
  });

  it("adds into the targeted nested group and nowhere else", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.setCurrentGroupPath(["g1", "g2"]));
    act(() => result.current.addConditionToTree("site", "eq", "new"));

    const tree = result.current.conditionTree;
    const g1 = groupById(tree, "g1")!;
    const g2 = g1.items.find((i) => i.id === "g2") as ConditionGroup;
    expect(g2.items).toHaveLength(2);
    expect(g2.items[1]).toMatchObject({ field: "site", value: "new" });
    expect(ids(g1.items)).toEqual(["c2", "g2"]);
    expect(ids(tree.items)).toEqual(["c1", "g1"]);
  });

  it("does not mutate the previous tree", () => {
    const { result } = setup(nestedTree());
    const before = result.current.conditionTree;
    const snapshot = structuredClone(before);
    act(() => result.current.setCurrentGroupPath(["g1"]));
    act(() => result.current.addConditionToTree("a", "eq", "b"));
    expect(before).toEqual(snapshot);
  });
});

describe("addGroup", () => {
  it("adds a group with the requested logic and an AND inner logic", () => {
    const { result } = setup();
    act(() => result.current.addGroup("OR", false));
    expect(result.current.conditionTree.items[0]).toMatchObject({
      type: "group",
      logic: "OR",
      internalLogic: "AND",
      items: [],
    });
  });

  it("negation wins over the requested logic", () => {
    const { result } = setup();
    act(() => result.current.addGroup("OR", true));
    expect(result.current.conditionTree.items[0]).toMatchObject({ logic: "NOT" });
  });

  it("adds a group inside the targeted group", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.setCurrentGroupPath(["g1"]));
    act(() => result.current.addGroup("AND", false));
    expect(groupById(result.current.conditionTree, "g1")!.items).toHaveLength(3);
  });
});

describe("removeItemFromTree", () => {
  it("removes a root item", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.removeItemFromTree("c1"));
    expect(ids(result.current.conditionTree.items)).toEqual(["g1"]);
  });

  it("removes a deeply nested item", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.removeItemFromTree("c3"));
    const g1 = groupById(result.current.conditionTree, "g1")!;
    const g2 = g1.items.find((i) => i.id === "g2") as ConditionGroup;
    expect(g2.items).toEqual([]);
  });

  it("removes a group together with everything in it", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.removeItemFromTree("g2"));
    expect(ids(groupById(result.current.conditionTree, "g1")!.items)).toEqual(["c2"]);
  });

  it("ignores an unknown id", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.removeItemFromTree("nope"));
    expect(result.current.conditionTree).toEqual(nestedTree());
  });

  it("moves the target out of a removed group so later additions are not lost", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.setCurrentGroupPath(["g1", "g2"]));
    act(() => result.current.removeItemFromTree("g2"));

    expect(result.current.currentGroupPath).toEqual(["g1"]);

    act(() => result.current.addConditionToTree("site", "eq", "kept"));
    expect(groupById(result.current.conditionTree, "g1")!.items).toHaveLength(2);
    expect(groupById(result.current.conditionTree, "g1")!.items[1]).toMatchObject({
      value: "kept",
    });
  });

  it("falls back to the root when an ancestor of the target is removed", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.setCurrentGroupPath(["g1", "g2"]));
    act(() => result.current.removeItemFromTree("g1"));
    expect(result.current.currentGroupPath).toEqual([]);
  });

  it("keeps the target when something else is removed", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.setCurrentGroupPath(["g1", "g2"]));
    act(() => result.current.removeItemFromTree("c1"));
    expect(result.current.currentGroupPath).toEqual(["g1", "g2"]);
  });
});

describe("updateGroupLogic", () => {
  it("changes the inner logic of a nested group only", () => {
    const { result } = setup(nestedTree());
    act(() => result.current.updateGroupLogic("g2", "OR"));

    const g1 = groupById(result.current.conditionTree, "g1")!;
    const g2 = g1.items.find((i) => i.id === "g2") as ConditionGroup;
    expect(g2.internalLogic).toBe("OR");
    expect(g1.internalLogic).toBe("AND");
    expect(result.current.conditionTree.internalLogic).toBe("AND");
  });
});

describe("findGroupPath", () => {
  it("returns the ids from the root down to the group", () => {
    const { result } = setup(nestedTree());
    expect(result.current.findGroupPath("g1")).toEqual(["g1"]);
    expect(result.current.findGroupPath("g2")).toEqual(["g1", "g2"]);
  });

  it("returns null for unknown ids and for condition ids", () => {
    const { result } = setup(nestedTree());
    expect(result.current.findGroupPath("nope")).toBeNull();
    expect(result.current.findGroupPath("c1")).toBeNull();
  });
});

describe("referential stability", () => {
  it("returns the same object when nothing changed (safe as an effect dependency)", () => {
    const { result, rerender } = setup();
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("keeps the callbacks that do not depend on state stable across updates", () => {
    const { result } = setup(nestedTree());
    const { removeItemFromTree, updateGroupLogic, flatConditionsToTree } = result.current;
    act(() => result.current.addGroup("AND", false));
    expect(result.current.removeItemFromTree).toBe(removeItemFromTree);
    expect(result.current.updateGroupLogic).toBe(updateGroupLogic);
    expect(result.current.flatConditionsToTree).toBe(flatConditionsToTree);
  });
});
