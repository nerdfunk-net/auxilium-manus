import { describe, expect, it } from "vitest";

import { diffLineClass } from "./unified-diff-view";

describe("diffLineClass", () => {
  it("colours added and removed lines", () => {
    expect(diffLineClass("+hostname r1")).toBe("text-success-foreground");
    expect(diffLineClass("-hostname old")).toBe("text-destructive");
  });

  it("treats file headers as muted, not add/remove", () => {
    expect(diffLineClass("+++ b/r1.cfg")).toBe("text-muted-foreground");
    expect(diffLineClass("--- a/r1.cfg")).toBe("text-muted-foreground");
  });

  it("highlights hunk and file markers", () => {
    expect(diffLineClass("@@ -1,3 +1,4 @@")).toBe("text-step");
    expect(diffLineClass("diff --git a/r1.cfg b/r1.cfg")).toContain("font-semibold");
  });

  it("leaves context lines with the default colour", () => {
    expect(diffLineClass(" unchanged line")).toBe("text-foreground");
    expect(diffLineClass("")).toBe("text-foreground");
  });
});
