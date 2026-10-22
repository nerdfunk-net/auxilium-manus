import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useAgentSourcesMutations } from "./use-agent-sources-mutations";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

beforeEach(() => {
  apiCall.mockReset();
  toast.mockReset();
});

function setup() {
  const { client, wrapper } = createQueryWrapper();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useAgentSourcesMutations(), { wrapper });
  return { result, invalidate };
}

const invalidatedKeys = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey);

const ALL = queryKeys.sourcesAgent.all;
const create = {
  source_id: "geo",
  transport: "http" as const,
  agent_id: "geo-agent",
  url: "http://geo:8080",
  credential_id: 7,
  max_concurrency: 4,
  max_request_bytes: 1048576,
  max_timeout_seconds: 60,
};

describe("useAgentSourcesMutations", () => {
  it("creates a source, refreshes the agent queries and says so", async () => {
    apiCall.mockResolvedValue({});
    const { result, invalidate } = setup();
    await act(() => result.current.createSource.mutateAsync(create));
    expect(apiCall).toHaveBeenCalledWith("sources/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(create),
    });
    expect(invalidatedKeys(invalidate)).toContainEqual(ALL);
    expect(toast).toHaveBeenCalledWith({ title: "Saved", description: "Agent source created." });
  });

  it("updates by encoded id and deletes by encoded id", async () => {
    apiCall.mockResolvedValue({});
    const { result, invalidate } = setup();
    await act(() => result.current.updateSource.mutateAsync({ sourceId: "a/b", data: { max_concurrency: 2 } }));
    expect(apiCall).toHaveBeenLastCalledWith("sources/agent/a%2Fb", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_concurrency: 2 }),
    });
    await act(() => result.current.deleteSource.mutateAsync("a/b"));
    expect(apiCall).toHaveBeenLastCalledWith("sources/agent/a%2Fb", { method: "DELETE" });
    expect(invalidatedKeys(invalidate).filter((key) => key === ALL)).toHaveLength(2);
  });

  it("reports a failed save as a destructive toast", async () => {
    apiCall.mockRejectedValue(new Error("nope"));
    const { result } = setup();
    await act(async () => {
      await expect(result.current.createSource.mutateAsync(create)).rejects.toThrow("nope");
    });
    expect(toast).toHaveBeenCalledWith({ title: "Error", description: "nope", variant: "destructive" });
  });

  describe("testConnection", () => {
    it("shows the latency on success", async () => {
      apiCall.mockResolvedValue({ success: true, message: "Agent is reachable.", latency_ms: 42 });
      const { result } = setup();
      await act(() => result.current.testConnection.mutateAsync({ source_id: "geo" }));
      expect(apiCall).toHaveBeenCalledWith("sources/agent/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: "geo" }),
      });
      expect(toast).toHaveBeenCalledWith({
        title: "Connection successful",
        description: "Agent is reachable. (42 ms)",
        variant: "default",
      });
    });

    it("refreshes the status badge after a result either way, so it cannot contradict the toast", async () => {
      const { result, invalidate } = setup();
      apiCall.mockResolvedValue({ success: true, message: "ok", latency_ms: 1 });
      await act(() => result.current.testConnection.mutateAsync({ source_id: "geo" }));
      expect(invalidatedKeys(invalidate)).toContainEqual(queryKeys.sourcesAgent.status("geo"));

      invalidate.mockClear();
      apiCall.mockResolvedValue({ success: false, message: "no", latency_ms: null });
      await act(() => result.current.testConnection.mutateAsync({ source_id: "geo" }));
      expect(invalidatedKeys(invalidate)).toContainEqual(queryKeys.sourcesAgent.status("geo"));
      expect(toast).toHaveBeenLastCalledWith({
        title: "Connection failed",
        description: "no",
        variant: "destructive",
      });
    });

    it("also refreshes after a request error", async () => {
      apiCall.mockRejectedValue(new Error("boom"));
      const { result, invalidate } = setup();
      await act(async () => {
        await expect(result.current.testConnection.mutateAsync({ source_id: "geo" })).rejects.toThrow();
      });
      expect(invalidatedKeys(invalidate)).toContainEqual(queryKeys.sourcesAgent.status("geo"));
    });
  });
});
