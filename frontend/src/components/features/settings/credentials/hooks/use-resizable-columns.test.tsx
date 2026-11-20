import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  MAX_COLUMN_WIDTH,
  useResizableColumns,
  type ResizableColumn,
} from "./use-resizable-columns";

const COLUMNS: readonly ResizableColumn[] = [
  { key: "a", defaultWidth: 100, minWidth: 50 },
  { key: "b", defaultWidth: 80, minWidth: 40, maxWidth: 200 },
];
const KEY = "resizable-columns:test-table";

beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

describe("useResizableColumns", () => {
  it("starts at the default widths", () => {
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    expect(result.current.widths).toEqual({ a: 100, b: 80 });
  });

  it("never goes below the minimum width", () => {
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    act(() => result.current.resizeBy("a", -1000, 100));
    expect(result.current.widths.a).toBe(50);
  });

  it("never goes above the default maximum when dragged far", () => {
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    act(() => result.current.resizeBy("a", 100000, 100));
    expect(result.current.widths.a).toBe(MAX_COLUMN_WIDTH);
  });

  it("uses a column's own maximum when it has one", () => {
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    act(() => result.current.resizeBy("b", 5000, 80));
    expect(result.current.widths.b).toBe(200);
  });

  it("clamps a huge stored width instead of building an arbitrarily wide grid", () => {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ a: 9_999_999, b: 9_999_999 }),
    );
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    expect(result.current.widths).toEqual({ a: MAX_COLUMN_WIDTH, b: 200 });
  });

  it("clamps a stored width below the minimum and ignores non-numbers", () => {
    window.localStorage.setItem(KEY, JSON.stringify({ a: 1, b: "wide" }));
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    expect(result.current.widths).toEqual({ a: 50, b: 80 });
  });

  it("falls back to the defaults for bad JSON", () => {
    window.localStorage.setItem(KEY, "{not json");
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    expect(result.current.widths).toEqual({ a: 100, b: 80 });
  });

  it("stores a committed width and gives it back on the next mount", () => {
    const first = renderHook(() => useResizableColumns("test-table", COLUMNS));
    act(() => first.result.current.resizeBy("a", 40, 100));
    act(() => first.result.current.commit());
    first.unmount();
    const second = renderHook(() => useResizableColumns("test-table", COLUMNS));
    expect(second.result.current.widths.a).toBe(140);
  });

  it("reset restores and stores the defaults", () => {
    const { result } = renderHook(() =>
      useResizableColumns("test-table", COLUMNS),
    );
    act(() => result.current.resizeBy("a", 40, 100));
    act(() => result.current.reset());
    expect(result.current.widths).toEqual({ a: 100, b: 80 });
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? "{}")).toEqual({
      a: 100,
      b: 80,
    });
  });
});
