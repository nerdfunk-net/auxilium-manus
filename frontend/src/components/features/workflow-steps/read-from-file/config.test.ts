import { describe, expect, it } from "vitest";

import { buildReadFromFileConfig } from "./config";

describe("buildReadFromFileConfig", () => {
  it("fills defaults for an empty config (mirrors backend get_config)", () => {
    expect(buildReadFromFileConfig({})).toEqual({
      source: "filesystem",
      git_repository_id: null,
      path: "",
      format: "auto",
      destination_path: "data",
      overwrite: false,
    });
  });

  it("coerces an unknown source to filesystem", () => {
    expect(buildReadFromFileConfig({ source: "bogus" }).source).toBe("filesystem");
  });

  it("coerces an unknown format to auto", () => {
    expect(buildReadFromFileConfig({ format: "toml" }).format).toBe("auto");
  });

  it("falls back to 'data' for an empty destination_path", () => {
    expect(buildReadFromFileConfig({ destination_path: "   " }).destination_path).toBe("data");
  });

  it("applies the patch over the normalized config and preserves unrelated keys", () => {
    const result = buildReadFromFileConfig(
      { source: "git", git_repository_id: 3, path: "a.yaml", overwrite: true },
      { path: "b.json" },
    );
    expect(result).toMatchObject({
      source: "git",
      git_repository_id: 3,
      path: "b.json",
      overwrite: true,
    });
  });
});
