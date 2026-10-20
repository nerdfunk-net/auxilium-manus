import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useSettingsMutations } from "./use-settings-mutations";

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
  const { result } = renderHook(() => useSettingsMutations(), { wrapper });
  return { result, invalidate };
}

const invalidatedKeys = (spy: { mock: { calls: unknown[][] } }) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown }).queryKey);

const JSON_HEADERS = { "Content-Type": "application/json" };

describe("useSettingsMutations", () => {
  it("createSetting posts the payload and invalidates the list and the new key", async () => {
    apiCall.mockResolvedValue({ key: "mail" });
    const { result, invalidate } = setup();
    const data = { key: "mail", value: { a: 1 } };

    await act(async () => {
      await result.current.createSetting.mutateAsync(data);
    });

    expect(apiCall).toHaveBeenCalledWith("settings", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    });
    expect(invalidatedKeys(invalidate)).toEqual([
      queryKeys.settings.all,
      queryKeys.settings.detail("mail"),
    ]);
    expect(toast).toHaveBeenCalledWith({ title: "Saved", description: "Setting created." });
  });

  it("updateSetting URL-encodes the key", async () => {
    apiCall.mockResolvedValue({ key: "a/b c" });
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.updateSetting.mutateAsync({ key: "a/b c", data: { value: { x: 1 } } });
    });

    expect(apiCall).toHaveBeenCalledWith("settings/a%2Fb%20c", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ value: { x: 1 } }),
    });
    expect(invalidatedKeys(invalidate)).toContainEqual(queryKeys.settings.detail("a/b c"));
  });

  it("deleteSetting invalidates using the requested key (the API returns nothing)", async () => {
    apiCall.mockResolvedValue(undefined);
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.deleteSetting.mutateAsync("old");
    });

    expect(apiCall).toHaveBeenCalledWith("settings/old", { method: "DELETE" });
    expect(invalidatedKeys(invalidate)).toEqual([
      queryKeys.settings.all,
      queryKeys.settings.detail("old"),
    ]);
    expect(toast).toHaveBeenCalledWith({ title: "Removed", description: "Setting deleted." });
  });

  describe("upsertSetting", () => {
    it("PUTs the value and description when the setting exists", async () => {
      apiCall.mockResolvedValue({ key: "k" });
      const { result } = setup();

      await act(async () => {
        await result.current.upsertSetting.mutateAsync({
          key: "k",
          value: { v: 1 },
          description: "d",
          exists: true,
        });
      });

      expect(apiCall).toHaveBeenCalledWith("settings/k", {
        method: "PUT",
        headers: JSON_HEADERS,
        body: JSON.stringify({ value: { v: 1 }, description: "d" }),
      });
    });

    it("POSTs the key as well when the setting does not exist", async () => {
      apiCall.mockResolvedValue({ key: "k" });
      const { result } = setup();

      await act(async () => {
        await result.current.upsertSetting.mutateAsync({
          key: "k",
          value: { v: 1 },
          exists: false,
        });
      });

      expect(apiCall).toHaveBeenCalledWith("settings", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ key: "k", value: { v: 1 } }),
      });
      expect(toast).toHaveBeenCalledWith({
        title: "Saved",
        description: "Configuration saved.",
      });
    });
  });

  it.each([
    ["createSetting", (r: ReturnType<typeof setup>["result"]) =>
      r.current.createSetting.mutateAsync({ key: "k", value: {} })],
    ["updateSetting", (r: ReturnType<typeof setup>["result"]) =>
      r.current.updateSetting.mutateAsync({ key: "k", data: {} })],
    ["deleteSetting", (r: ReturnType<typeof setup>["result"]) =>
      r.current.deleteSetting.mutateAsync("k")],
    ["upsertSetting", (r: ReturnType<typeof setup>["result"]) =>
      r.current.upsertSetting.mutateAsync({ key: "k", value: {}, exists: true })],
  ])("%s toasts the error and does not invalidate on failure", async (_name, run) => {
    apiCall.mockRejectedValue(new Error("denied"));
    const { result, invalidate } = setup();

    await act(async () => {
      await expect(run(result)).rejects.toThrow("denied");
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith({
      title: "Error",
      description: "denied",
      variant: "destructive",
    });
  });

  describe("Nautobot source rows", () => {
    it("refresh the configured-sources list that pages without settings:read use", async () => {
      apiCall.mockResolvedValue({ key: "sources.nautobot.lab" });
      const { result, invalidate } = setup();
      await act(async () => {
        await result.current.upsertSetting.mutateAsync({
          key: "sources.nautobot.lab",
          value: { url: "https://nb.example" },
          exists: false,
        });
      });
      expect(invalidatedKeys(invalidate)).toContainEqual(
        queryKeys.sourcesNautobot.configuredSources(),
      );
    });

    it("also refresh it after a delete", async () => {
      apiCall.mockResolvedValue(undefined);
      const { result, invalidate } = setup();
      await act(async () => {
        await result.current.deleteSetting.mutateAsync("sources.nautobot.lab");
      });
      expect(invalidatedKeys(invalidate)).toContainEqual(
        queryKeys.sourcesNautobot.configuredSources(),
      );
    });

    it("leave it alone for any other setting", async () => {
      apiCall.mockResolvedValue({ key: "mail" });
      const { result, invalidate } = setup();
      await act(async () => {
        await result.current.createSetting.mutateAsync({ key: "mail", value: {} });
      });
      expect(invalidatedKeys(invalidate)).not.toContainEqual(
        queryKeys.sourcesNautobot.configuredSources(),
      );
    });
  });
});
