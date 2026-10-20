import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import { useNautobotSourceCredentials } from "./use-nautobot-source-credentials";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const LIST = {
  sources: [
    { source_id: "lab", url: "https://lab.example", token_configured: true },
    { source_id: "dev", url: "https://dev.example", token_configured: false },
    { source_id: "bare", url: "", token_configured: true },
  ],
};

function setup(options: Parameters<typeof useNautobotSourceCredentials>[0]) {
  const { wrapper } = createQueryWrapper();
  return renderHook(() => useNautobotSourceCredentials(options), { wrapper });
}

beforeEach(() => {
  apiCall.mockReset();
  apiCall.mockResolvedValue(LIST);
});

describe("useNautobotSourceCredentials", () => {
  it("finds the chosen source and reports it ready", async () => {
    const { result } = setup({ sourceId: "lab" });
    await waitFor(() => expect(result.current.url).toBe("https://lab.example"));
    expect(result.current).toMatchObject({
      sourceId: "lab",
      tokenConfigured: true,
      isReady: true,
      isError: false,
    });
  });

  it("matches the id without regard to case or surrounding spaces", async () => {
    const { result } = setup({ sourceId: "  LAB " });
    await waitFor(() => expect(result.current.url).toBe("https://lab.example"));
    expect(result.current.sourceId).toBe("lab");
  });

  it("is not ready without a token", async () => {
    const { result } = setup({ sourceId: "dev" });
    await waitFor(() => expect(result.current.url).toBe("https://dev.example"));
    expect(result.current.tokenConfigured).toBe(false);
    expect(result.current.isReady).toBe(false);
  });

  it("is not ready without a URL", async () => {
    const { result } = setup({ sourceId: "bare" });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isReady).toBe(false);
  });

  it("reports an unknown source as empty and not ready", async () => {
    const { result } = setup({ sourceId: "gone" });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current).toMatchObject({ url: "", tokenConfigured: false, isReady: false });
  });

  it("does not ask the server without a source id or while disabled", async () => {
    setup({ sourceId: undefined });
    setup({ sourceId: "lab", enabled: false });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("flags a failed request", async () => {
    apiCall.mockRejectedValue(new Error("403"));
    const { result } = setup({ sourceId: "lab" });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.isReady).toBe(false);
  });

  it("returns the same object when nothing changed", async () => {
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useNautobotSourceCredentials({ sourceId: "lab" }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isReady).toBe(true));
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
