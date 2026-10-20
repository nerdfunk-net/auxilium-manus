import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useNautobotConfiguredSourcesQuery } from "./use-nautobot-configured-sources-query";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const SOURCES = [{ source_id: "lab", url: "https://nb.example", token_configured: true }];

beforeEach(() => {
  apiCall.mockReset();
  apiCall.mockResolvedValue({ sources: SOURCES });
});

describe("useNautobotConfiguredSourcesQuery", () => {
  it("reads the sources from the endpoint that needs only sources.nautobot:read", async () => {
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useNautobotConfiguredSourcesQuery(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(SOURCES));
    expect(apiCall).toHaveBeenCalledWith("sources/nautobot/configured-sources", { method: "GET" });
  });

  it("does not fetch while disabled", async () => {
    const { wrapper } = createQueryWrapper();
    renderHook(() => useNautobotConfiguredSourcesQuery({ enabled: false }), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("caches under the key the settings mutations invalidate", async () => {
    const { wrapper, client } = createQueryWrapper();
    const { result } = renderHook(() => useNautobotConfiguredSourcesQuery(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(client.getQueryData(queryKeys.sourcesNautobot.configuredSources())).toEqual(SOURCES);
  });

  it("passes an error on, for the caller to show", async () => {
    apiCall.mockRejectedValue(new Error("Permission denied: sources.nautobot:read required"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useNautobotConfiguredSourcesQuery(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("sources.nautobot:read");
  });
});
