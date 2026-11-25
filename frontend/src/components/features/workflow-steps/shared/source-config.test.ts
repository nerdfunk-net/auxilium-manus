import { describe, expect, it } from "vitest";

import { makeSourceConfig } from "./source-config";

describe("makeSourceConfig", () => {
  const plain = makeSourceConfig("demo_source_id");
  const lower = makeSourceConfig("demo_source_id", { lowercase: true });

  it("keeps the key", () => {
    expect(plain.key).toBe("demo_source_id");
  });

  it("reads a trimmed id", () => {
    expect(plain.idFromConfig({ demo_source_id: "  Lab-1 " })).toBe("Lab-1");
  });

  it("lowercases only when asked", () => {
    expect(lower.idFromConfig({ demo_source_id: " Lab-1 " })).toBe("lab-1");
  });

  it("returns an empty id for a missing, blank or non-string value", () => {
    for (const config of [{}, { demo_source_id: "" }, { demo_source_id: "   " }, { demo_source_id: 3 }]) {
      expect(plain.idFromConfig(config)).toBe("");
    }
  });

  it("is configured when an id is set", () => {
    expect(plain.isConfigured({ demo_source_id: "lab" })).toBe(true);
    expect(plain.isConfigured({ demo_source_id: " " })).toBe(false);
  });
});
