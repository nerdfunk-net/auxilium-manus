import { describe, expect, it } from "vitest";

import { buildEnrichAttributesConfig } from "./config";

describe("buildEnrichAttributesConfig", () => {
  it("fills defaults for an empty config (mirrors backend get_config)", () => {
    expect(buildEnrichAttributesConfig({})).toEqual({
      source: "filesystem",
      git_repository_id: null,
      refresh_repository: false,
      allow_stale_repository: false,
      path: "",
      delimiter: ";",
      key_column: "",
      device_attribute_path: "",
      match_mode: "match",
      case_insensitive: false,
      destination_path: "data",
      overwrite: false,
    });
  });

  it("keeps refresh_repository only when it is exactly true", () => {
    expect(buildEnrichAttributesConfig({ refresh_repository: true }).refresh_repository).toBe(true);
    expect(buildEnrichAttributesConfig({ refresh_repository: "yes" }).refresh_repository).toBe(
      false,
    );
  });

  it("coerces unknown source and match_mode to their defaults", () => {
    const result = buildEnrichAttributesConfig({ source: "bogus", match_mode: "regex" });
    expect(result.source).toBe("filesystem");
    expect(result.match_mode).toBe("match");
  });

  it("keeps contains and git settings", () => {
    expect(
      buildEnrichAttributesConfig({
        source: "git",
        git_repository_id: 3,
        match_mode: "contains",
        case_insensitive: true,
      }),
    ).toMatchObject({
      source: "git",
      git_repository_id: 3,
      match_mode: "contains",
      case_insensitive: true,
    });
  });

  it("falls back to ';' and 'data' for empty delimiter and destination", () => {
    const result = buildEnrichAttributesConfig({ delimiter: "", destination_path: "   " });
    expect(result.delimiter).toBe(";");
    expect(result.destination_path).toBe("data");
  });

  it("applies the patch over the normalized config", () => {
    const result = buildEnrichAttributesConfig(
      { key_column: "serial", overwrite: true },
      { key_column: "sn" },
    );
    expect(result).toMatchObject({ key_column: "sn", overwrite: true });
  });
});
