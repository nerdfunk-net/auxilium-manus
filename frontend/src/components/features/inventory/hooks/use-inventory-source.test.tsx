import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import { useInventorySource } from "./use-inventory-source";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

beforeEach(() => {
  apiCall.mockReset();
});

describe("useInventorySource", () => {
  it("reports the settings error instead of looking like 'no source configured'", async () => {
    apiCall.mockRejectedValue(new Error("Permission denied: settings:read required"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasSources).toBe(false);
    expect(result.current.error).toBe("Permission denied: settings:read required");
  });

  it("has no error and no source when the list is simply empty", async () => {
    apiCall.mockResolvedValue({ settings: [], total: 0 });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasSources).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("returns the same object when nothing changed", async () => {
    apiCall.mockResolvedValue({ settings: [], total: 0 });
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
