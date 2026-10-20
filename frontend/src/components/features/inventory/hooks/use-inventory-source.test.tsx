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
    apiCall.mockRejectedValue(new Error("Permission denied: sources.nautobot:read required"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasSources).toBe(false);
    expect(result.current.error).toBe("Permission denied: sources.nautobot:read required");
  });

  it("has no error and no source when the list is simply empty", async () => {
    apiCall.mockResolvedValue({ sources: [] });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.hasSources).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("uses the first configured source, with its URL and readiness", async () => {
    apiCall.mockResolvedValue({
      sources: [
        { source_id: "lab", url: "https://lab.example", token_configured: true },
        { source_id: "dev", url: "https://dev.example", token_configured: true },
      ],
    });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.hasSources).toBe(true));
    expect(result.current).toMatchObject({
      sourceId: "lab",
      nautobotUrl: "https://lab.example",
      isReady: true,
      error: null,
    });
    expect(apiCall.mock.calls[0]![0]).toBe("sources/nautobot/configured-sources");
  });

  it("is not ready while the source has no token", async () => {
    apiCall.mockResolvedValue({
      sources: [{ source_id: "lab", url: "https://lab.example", token_configured: false }],
    });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.hasSources).toBe(true));
    expect(result.current.isReady).toBe(false);
  });

  it("returns the same object when nothing changed", async () => {
    apiCall.mockResolvedValue({ sources: [] });
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useInventorySource(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
