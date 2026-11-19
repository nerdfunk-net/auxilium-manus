import { describe, expect, it } from "vitest";

import { GIT_CATEGORIES, gitCategoryLabel } from "./git-repository-utils";

describe("GIT_CATEGORIES", () => {
  it("offers both CSV categories that Ask the Net's file comparison reads", () => {
    const values = GIT_CATEGORIES.map((entry) => entry.value);
    expect(values).toContain("csv_imports");
    expect(values).toContain("csv_exports");
  });

  it("has unique values and a label for each", () => {
    const values = GIT_CATEGORIES.map((entry) => entry.value);
    expect(new Set(values).size).toBe(values.length);
    for (const entry of GIT_CATEGORIES) {
      expect(entry.label.length).toBeGreaterThan(0);
    }
  });

  it("names the CSV categories for people, not as raw ids", () => {
    expect(gitCategoryLabel("csv_imports")).toMatch(/CSV/);
    expect(gitCategoryLabel("csv_exports")).toMatch(/CSV/);
    expect(gitCategoryLabel("unknown_thing")).toBe("unknown_thing");
  });
});
