import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { usePluginUI } from "@/components/features/workflows/hooks/use-plugin-ui";

import { getLoadedPluginUI, hasPluginUI, loadPluginUI } from "./plugin-ui-registry";

describe("plugin UI registry (lazy)", () => {
  it("knows which steps have a panel without loading any", () => {
    expect(hasPluginUI("stop-here")).toBe(true);
    expect(hasPluginUI("no-such-step")).toBe(false);
  });

  it("loads a step's panels on demand and caches them", async () => {
    const ui = await loadPluginUI("stop-here");
    expect(ui?.ConfigPanel).toBeTypeOf("function");
    expect(getLoadedPluginUI("stop-here")).toBe(ui);
    expect(await loadPluginUI("stop-here")).toBe(ui);
  });

  it("resolves to undefined for an unknown step", async () => {
    expect(await loadPluginUI("no-such-step")).toBeUndefined();
  });

  it("usePluginUI returns undefined first, then the loaded panels", async () => {
    const { result } = renderHook(() => usePluginUI("fan-in"));
    await waitFor(() => expect(result.current?.ConfigPanel).toBeTypeOf("function"));
  });

  it("usePluginUI stays undefined without an id or for an unknown step", () => {
    expect(renderHook(() => usePluginUI(undefined)).result.current).toBeUndefined();
    expect(renderHook(() => usePluginUI("no-such-step")).result.current).toBeUndefined();
  });
});
