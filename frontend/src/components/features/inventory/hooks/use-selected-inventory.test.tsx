import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DeviceInfo } from "../types/device-selector";
import { useSelectedInventory } from "./use-selected-inventory";

const device = (id: string, name = `sw-${id}`): DeviceInfo =>
  ({ id, name }) as unknown as DeviceInfo;

const ids = (result: { current: ReturnType<typeof useSelectedInventory> }) =>
  result.current.selectedDevices.map((d) => d.id);

describe("useSelectedInventory", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useSelectedInventory());
    expect(result.current.selectedDevices).toEqual([]);
    expect(result.current.selectedCount).toBe(0);
    expect(result.current.removalSelectedIds.size).toBe(0);
  });

  it("returns the same object when nothing changed", () => {
    const { result, rerender } = renderHook(() => useSelectedInventory());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("adds devices and replaces a device that is added again", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b")]));
    act(() => result.current.addDevices([device("b", "renamed"), device("c")]));
    expect(ids(result)).toEqual(["a", "b", "c"]);
    expect(result.current.selectedDevices[1]!.name).toBe("renamed");
    expect(result.current.selectedCount).toBe(3);
  });

  it("removes one device and forgets its removal mark", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b")]));
    act(() => result.current.toggleRemovalSelect("a", true));
    act(() => result.current.removeDevice("a"));
    expect(ids(result)).toEqual(["b"]);
    expect(result.current.removalSelectedIds.has("a")).toBe(false);
  });

  it("keeps the removal set object when the removed device was not marked", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b")]));
    act(() => result.current.toggleRemovalSelect("b", true));
    const before = result.current.removalSelectedIds;
    act(() => result.current.removeDevice("a"));
    expect(result.current.removalSelectedIds).toBe(before);
  });

  it("ignores removing an unknown device", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a")]));
    act(() => result.current.removeDevice("zzz"));
    expect(ids(result)).toEqual(["a"]);
  });

  it("removes several devices and their marks", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b"), device("c")]));
    act(() => result.current.toggleRemovalSelect("a", true));
    act(() => result.current.toggleRemovalSelect("c", true));
    act(() => result.current.removeDevices(["a", "b"]));
    expect(ids(result)).toEqual(["c"]);
    expect([...result.current.removalSelectedIds]).toEqual(["c"]);
  });

  it("toggles a removal mark on and off", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a")]));
    act(() => result.current.toggleRemovalSelect("a", true));
    expect(result.current.removalSelectedIds.has("a")).toBe(true);
    act(() => result.current.toggleRemovalSelect("a", false));
    expect(result.current.removalSelectedIds.has("a")).toBe(false);
  });

  it("marks everything for removal and clears the marks again", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b")]));
    act(() => result.current.selectAllForRemoval(true));
    expect([...result.current.removalSelectedIds].sort()).toEqual(["a", "b"]);
    act(() => result.current.selectAllForRemoval(false));
    expect(result.current.removalSelectedIds.size).toBe(0);
  });

  it("selects all for removal over the devices added since the last render", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a")]));
    act(() => result.current.addDevices([device("b")]));
    act(() => result.current.selectAllForRemoval(true));
    expect([...result.current.removalSelectedIds].sort()).toEqual(["a", "b"]);
  });

  it("removes exactly the marked devices", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a"), device("b"), device("c")]));
    act(() => result.current.toggleRemovalSelect("b", true));
    act(() => result.current.removeSelectedDevices());
    expect(ids(result)).toEqual(["a", "c"]);
    expect(result.current.removalSelectedIds.size).toBe(0);
  });

  it("replaceAll swaps the selection and clears the marks", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a")]));
    act(() => result.current.toggleRemovalSelect("a", true));
    act(() => result.current.replaceAll([device("x"), device("y"), device("x", "again")]));
    expect(ids(result)).toEqual(["x", "y"]);
    expect(result.current.selectedDevices[0]!.name).toBe("again");
    expect(result.current.removalSelectedIds.size).toBe(0);
  });

  it("clear empties the selection and the marks", () => {
    const { result } = renderHook(() => useSelectedInventory());
    act(() => result.current.addDevices([device("a")]));
    act(() => result.current.toggleRemovalSelect("a", true));
    act(() => result.current.clear());
    expect(result.current.selectedCount).toBe(0);
    expect(result.current.removalSelectedIds.size).toBe(0);
  });
});
