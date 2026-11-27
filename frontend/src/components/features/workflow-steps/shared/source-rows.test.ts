import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * W14-02: a step panel shows its source (id, "Not configured", the Configure / Edit button)
 * through `SourceRow`, not with its own copy of that block.
 */
const STEPS_DIR = path.resolve(__dirname, "..");

/** discover-network shows a hint between the id and the button and no "Not configured" line
 * (maintainer decision 2026-11-27): it keeps its own block. */
const OWN_BLOCK = new Set(["discover-network/index.tsx"]);

const BUTTON_TEXT = /"Configure Source"/g;

function panelSources(dir: string): { file: string; text: string }[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return panelSources(full);
    if (!entry.name.endsWith(".tsx") || entry.name.includes(".test."))
      return [];
    if (entry.name === "source-row.tsx") return [];
    return [
      {
        file: path.relative(STEPS_DIR, full),
        text: readFileSync(full, "utf8"),
      },
    ];
  });
}

export function ownSourceBlocks(text: string): number {
  return text.match(BUTTON_TEXT)?.length ?? 0;
}

describe("source rows", () => {
  it("are SourceRow, not a copy of its markup", () => {
    const sources = panelSources(STEPS_DIR);
    // The panels live in one directory per step: an empty scan would pass by accident.
    expect(sources.length).toBeGreaterThan(100);
    const found = sources
      .filter(
        ({ file, text }) => !OWN_BLOCK.has(file) && ownSourceBlocks(text) > 0,
      )
      .map(({ file }) => file);
    expect(found).toEqual([]);
  });

  it("the exceptions still have their own block", () => {
    const sources = panelSources(STEPS_DIR);
    for (const file of OWN_BLOCK) {
      const own = sources.find((source) => source.file === file);
      expect(own && ownSourceBlocks(own.text)).toBeGreaterThan(0);
    }
  });

  it("the scan recognises the copied button", () => {
    expect(ownSourceBlocks(`{id ? "Edit Source" : "Configure Source"}`)).toBe(
      1,
    );
    expect(
      ownSourceBlocks(
        `<SourceRow label="k" badge="b" sourceId={id} onOpen={open} />`,
      ),
    ).toBe(0);
  });
});
