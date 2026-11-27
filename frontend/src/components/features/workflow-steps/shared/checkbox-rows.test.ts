import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * W14-04: a step panel uses `CheckboxField` for the standard boolean row (checkbox + monospace key
 * label + optional hint) instead of writing its markup by hand.
 */
const STEPS_DIR = path.resolve(__dirname, "..");

const HAND_WRITTEN_ROW =
  /<div[^>]*className="flex items-start gap-2">\s*<Checkbox\b[\s\S]{0,400}?className="mt-0\.5"\s*\/>\s*<div className="space-y-0\.5">\s*<Label[\s\S]{0,200}?className="font-mono text-xs font-medium"/g;

function panelSources(dir: string): { file: string; text: string }[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return panelSources(full);
    if (!entry.name.endsWith(".tsx") || entry.name.includes(".test."))
      return [];
    if (entry.name === "checkbox-field.tsx") return [];
    return [
      {
        file: path.relative(STEPS_DIR, full),
        text: readFileSync(full, "utf8"),
      },
    ];
  });
}

export function handWrittenRows(text: string): number {
  return text.match(HAND_WRITTEN_ROW)?.length ?? 0;
}

describe("standard checkbox rows", () => {
  it("are CheckboxField, not hand-written markup", () => {
    const sources = panelSources(STEPS_DIR);
    // The panels live in one directory per step: an empty scan would pass by accident.
    expect(sources.length).toBeGreaterThan(100);
    const found = sources
      .map(({ file, text }) => [file, handWrittenRows(text)] as const)
      .filter(([, count]) => count > 0);
    expect(found).toEqual([]);
  });

  it("the scan recognises the hand-written row", () => {
    const row = `<div className="flex items-start gap-2">
        <Checkbox
          id="x"
          checked={x}
          onCheckedChange={(checked) => patch({ x: checked === true })}
          className="mt-0.5"
        />
        <div className="space-y-0.5">
          <Label htmlFor="x" className="font-mono text-xs font-medium">x</Label>`;
    expect(handWrittenRows(row)).toBe(1);
    expect(
      handWrittenRows(
        `<CheckboxField id="x" label="x" checked onCheckedChange={f} />`,
      ),
    ).toBe(0);
  });
});
