import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const STEPS_DIR = path.resolve(__dirname, "../components/features/workflow-steps");
const REGISTRY = readFileSync(path.resolve(__dirname, "plugin-ui-registry.ts"), "utf8");

const LOADERS = [
  ...REGISTRY.matchAll(
    /"?([a-z0-9-]+)"?: \(\) => import\("@\/components\/features\/workflow-steps\/([^"]+)"\)\.then\(\(m\) => m\.(\w+)\)/g,
  ),
].map(([, id, dir, exportName]) => ({ id, dir, exportName }));

const pascal = (id: string) =>
  id
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join("");

describe("plugin UI registry convention (F-F, W14-10)", () => {
  it("finds the loaders", () => {
    expect(LOADERS.length).toBeGreaterThan(100);
  });

  it.each(LOADERS)("$id: directory and export follow the step id", ({ id, dir, exportName }) => {
    expect(dir).toBe(id);
    expect(exportName).toBe(`${pascal(id)}Plugin`);
    expect(existsSync(path.join(STEPS_DIR, dir, "index.tsx"))).toBe(true);
  });

  it("has a loader for every step directory that has a panel", () => {
    const ids = new Set(LOADERS.map((loader) => loader.id));
    const withPanel = readdirSync(STEPS_DIR, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && entry.name !== "shared")
      .filter((entry) => existsSync(path.join(STEPS_DIR, entry.name, "index.tsx")))
      .map((entry) => entry.name)
      .filter((name) => !ids.has(name));
    expect(withPanel).toEqual([]);
  });

  it("has no duplicate ids", () => {
    const ids = LOADERS.map((loader) => loader.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
