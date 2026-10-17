import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useToast, useToastStore } from "./use-toast";

beforeEach(() => {
  vi.useFakeTimers();
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useToast", () => {
  it("returns a referentially stable object while nothing changes", () => {
    const { result, rerender } = renderHook(() => useToast());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("generates unique 16-char hex ids", () => {
    const { result } = renderHook(() => useToast());
    act(() => {
      result.current.toast({ description: "a" });
      result.current.toast({ description: "b" });
    });
    const ids = useToastStore.getState().toasts.map((toast) => toast.id);
    expect(new Set(ids).size).toBe(2);
    for (const id of ids) {
      expect(id).toMatch(/^[0-9a-f]{16}$/);
    }
  });

  it("auto-dismisses after 5 seconds", () => {
    const { result } = renderHook(() => useToast());
    act(() => {
      result.current.toast({ description: "bye" });
    });
    expect(useToastStore.getState().toasts).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
