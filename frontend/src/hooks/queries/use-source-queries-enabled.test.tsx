import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNautobotSources } from "@/components/features/templates/hooks/use-nautobot-sources";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useBatfishSourcesQuery } from "./use-batfish-sources-query";
import { useMattermostSourcesQuery } from "./use-mattermost-sources-query";
import { usePyATSSourcesQuery } from "./use-pyats-sources-query";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

beforeEach(() => {
  apiCall.mockReset();
  apiCall.mockResolvedValue({ sources: [], settings: [] });
});

// The import dialogs are always mounted on the workflow builder page and pass
// `enabled={dialog is open}`: a closed dialog must not fetch anything.
describe.each([
  ["useMattermostSourcesQuery", useMattermostSourcesQuery, "sources/mattermost"],
  ["useBatfishSourcesQuery", useBatfishSourcesQuery, "sources/batfish"],
  ["usePyATSSourcesQuery", usePyATSSourcesQuery, "sources/pyats"],
  ["useNautobotSources", useNautobotSources, "settings?key_prefix="],
])("%s", (_name, useHook, endpointPrefix) => {
  it("fetches by default", async () => {
    const { wrapper } = createQueryWrapper();
    renderHook(() => useHook(), { wrapper });
    await waitFor(() => expect(apiCall).toHaveBeenCalled());
    expect(apiCall.mock.calls[0][0]).toContain(endpointPrefix);
  });

  it("does not fetch while disabled, and fetches once enabled", async () => {
    const { wrapper } = createQueryWrapper();
    const { rerender } = renderHook(({ enabled }) => useHook({ enabled }), {
      wrapper,
      initialProps: { enabled: false },
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(apiCall).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(apiCall).toHaveBeenCalledTimes(1));
  });
});
