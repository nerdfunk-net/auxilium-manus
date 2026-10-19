import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

const STOP_HERE = "@/components/features/workflow-steps/stop-here";

/** A fresh registry module, so the loaded/in-flight caches start empty. */
async function freshRegistry() {
  vi.resetModules();
  return import("./plugin-ui-registry");
}

afterEach(() => {
  vi.doUnmock(STOP_HERE);
  vi.resetModules();
});

describe("hasPluginUI", () => {
  it("is true for steps with a panel and false otherwise", async () => {
    const { hasPluginUI } = await freshRegistry();
    expect(hasPluginUI("run-command")).toBe(true);
    expect(hasPluginUI("label")).toBe(true);
    expect(hasPluginUI("no-such-step")).toBe(false);
    expect(hasPluginUI("")).toBe(false);
  });

  // Plugin ids come from the backend; an id such as "constructor" must not be mistaken
  // for a registered panel (`in` also matches inherited Object.prototype keys).
  it.each(["constructor", "toString", "hasOwnProperty", "__proto__"])(
    "does not treat the inherited key %s as a panel",
    async (key) => {
      const { hasPluginUI } = await freshRegistry();
      expect(hasPluginUI(key)).toBe(false);
    },
  );
});

describe("loadPluginUI", () => {
  it("resolves undefined for an unknown step without loading anything", async () => {
    const { loadPluginUI } = await freshRegistry();
    await expect(loadPluginUI("no-such-step")).resolves.toBeUndefined();
  });

  it.each(["constructor", "toString"])(
    "resolves undefined for the inherited key %s instead of throwing",
    async (key) => {
      const { loadPluginUI } = await freshRegistry();
      await expect(loadPluginUI(key)).resolves.toBeUndefined();
    },
  );

  it("loads a panel once, then serves it from the cache", async () => {
    const { loadPluginUI, getLoadedPluginUI } = await freshRegistry();
    expect(getLoadedPluginUI("stop-here")).toBeUndefined();

    const first = await loadPluginUI("stop-here");
    expect(first).toBeDefined();
    expect(getLoadedPluginUI("stop-here")).toBe(first);
    expect(await loadPluginUI("stop-here")).toBe(first);
  });

  it("shares one in-flight load between concurrent callers", async () => {
    const { loadPluginUI } = await freshRegistry();
    const a = loadPluginUI("stop-here");
    const b = loadPluginUI("stop-here");
    expect(a).toBe(b);
    expect(await a).toBe(await b);
  });

  it("does not remember a failed load, so the next call can succeed", async () => {
    let failing = true;
    const Sentinel = () => null;
    vi.doMock(STOP_HERE, () => {
      if (failing) throw new Error("chunk failed to load");
      return { StopHerePlugin: Sentinel };
    });
    const { loadPluginUI, getLoadedPluginUI } = await freshRegistry();

    await expect(loadPluginUI("stop-here")).rejects.toThrow();
    expect(getLoadedPluginUI("stop-here")).toBeUndefined();

    failing = false;
    await expect(loadPluginUI("stop-here")).resolves.toBe(Sentinel);
  });
});

// A panel module that throws on import (or no longer exports its component) would only show
// up when a user opens that step, so load every one of them here.
describe("every registered panel", () => {
  it("loads and exports a component", { timeout: 120_000 }, async () => {
    const source = readFileSync(path.resolve(__dirname, "plugin-ui-registry.ts"), "utf8");
    const ids = [...source.matchAll(/^ {2}"?([a-z0-9-]+)"?: \(\) => import/gm)].map((m) => m[1]);
    expect(ids.length).toBeGreaterThan(50);

    const { loadPluginUI } = await freshRegistry();
    const failures: string[] = [];
    for (const id of ids) {
      try {
        const ui = await loadPluginUI(id);
        if (!ui) failures.push(`${id}: no component exported`);
      } catch (error) {
        failures.push(`${id}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    expect(failures).toEqual([]);
  });
});

// Every backend step with a configuration form needs a panel here; a step added to
// registry.yaml without one (or a panel left behind for a removed step) shows up as drift.
describe("registry drift", () => {
  const registryYaml = path.resolve(__dirname, "../../../backend/workflow_steps/registry.yaml");
  // Steps the canvas handles without a config panel: the palette's "Step Group" is a container.
  const WITHOUT_PANEL = new Set(["step-group"]);

  it.skipIf(!existsSync(registryYaml))(
    "has a panel for every backend step and no panel for a removed step",
    async () => {
      const backendIds = [...readFileSync(registryYaml, "utf8").matchAll(/^ {2}- id: (\S+)/gm)].map(
        (match) => match[1],
      );
      expect(backendIds.length).toBeGreaterThan(50);

      const { hasPluginUI } = await freshRegistry();
      const missing = backendIds.filter((id) => !WITHOUT_PANEL.has(id) && !hasPluginUI(id));
      expect(missing).toEqual([]);

      // Reverse direction: read the registered ids from the source, since the loader table is private.
      const source = readFileSync(path.resolve(__dirname, "plugin-ui-registry.ts"), "utf8");
      const registered = [...source.matchAll(/^ {2}"?([a-z0-9-]+)"?: \(\) => import/gm)].map(
        (match) => match[1],
      );
      expect(registered.length).toBeGreaterThan(50);
      const backend = new Set(backendIds);
      expect(registered.filter((id) => !backend.has(id))).toEqual([]);
    },
  );
});
