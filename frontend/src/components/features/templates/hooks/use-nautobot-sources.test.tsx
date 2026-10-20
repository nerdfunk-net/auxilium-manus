import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import { useNautobotSources } from "./use-nautobot-sources";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

beforeEach(() => {
  apiCall.mockReset();
});

describe("useNautobotSources", () => {
  it("lists the source ids from the configured-sources endpoint", async () => {
    apiCall.mockResolvedValue({
      sources: [
        { source_id: "lab", url: "https://lab.example", token_configured: true },
        { source_id: "dev", url: "", token_configured: false },
      ],
    });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useNautobotSources(), { wrapper });
    await waitFor(() => expect(result.current.sources).toHaveLength(2));
    expect(result.current.sources).toEqual([{ sourceId: "lab" }, { sourceId: "dev" }]);
    expect(apiCall.mock.calls[0]![0]).toBe("sources/nautobot/configured-sources");
  });

  it("reports a failed request", async () => {
    apiCall.mockRejectedValue(new Error("403"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useNautobotSources(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.sources).toEqual([]);
  });

  it("returns the same object when nothing changed", async () => {
    apiCall.mockResolvedValue({ sources: [] });
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useNautobotSources(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
