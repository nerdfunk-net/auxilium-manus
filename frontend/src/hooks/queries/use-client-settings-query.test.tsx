import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import { useClientSettingsQuery } from "./use-client-settings-query";
import { useGeneralSettingsMutations } from "./use-general-settings-mutations";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

beforeEach(() => {
  apiCall.mockReset();
});

describe("useClientSettingsQuery", () => {
  it("reads the endpoint every signed-in user may call, not general/settings", async () => {
    apiCall.mockResolvedValue({ session_timeout_minutes: 7, switch_to_runs_on_start: false });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useClientSettingsQuery(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(apiCall).toHaveBeenCalledWith("general/client-settings", { method: "GET" });
    expect(result.current.data?.session_timeout_minutes).toBe(7);
  });

  it("refetches after an administrator saves the general settings", async () => {
    apiCall.mockResolvedValue({ session_timeout_minutes: 7, switch_to_runs_on_start: true });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(
      () => ({ query: useClientSettingsQuery(), mutations: useGeneralSettingsMutations() }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.query.data).toBeDefined());
    apiCall.mockClear();
    apiCall.mockResolvedValue({ session_timeout_minutes: 3, switch_to_runs_on_start: true });
    await act(async () => {
      await result.current.mutations.saveSettings.mutateAsync({
        session_timeout_minutes: 3,
        default_export_directory: "",
        switch_to_runs_on_start: true,
      });
    });
    await waitFor(() => expect(result.current.query.data?.session_timeout_minutes).toBe(3));
    expect(apiCall).toHaveBeenCalledWith("general/client-settings", { method: "GET" });
  });
});
