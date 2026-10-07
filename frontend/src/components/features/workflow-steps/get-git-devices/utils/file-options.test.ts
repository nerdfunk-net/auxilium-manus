import { describe, expect, it } from "vitest";

import {
  delimiterFromConfig,
  fileFormatFromConfig,
  multilineFromConfig,
  patternForFormat,
} from "./file-options";

describe("file options", () => {
  it("defaults to yaml, semicolon, single-line", () => {
    expect(fileFormatFromConfig({})).toBe("yaml");
    expect(delimiterFromConfig({})).toBe(";");
    expect(multilineFromConfig({})).toBe(false);
  });

  it("reads csv config and ignores unknown delimiters", () => {
    expect(fileFormatFromConfig({ file_format: "csv" })).toBe("csv");
    expect(delimiterFromConfig({ csv_delimiter: "\t" })).toBe("\t");
    expect(delimiterFromConfig({ csv_delimiter: "abc" })).toBe(";");
    expect(multilineFromConfig({ csv_multiline: true })).toBe(true);
  });

  it("switches the pattern only while it holds a default", () => {
    expect(patternForFormat("*.yaml", "csv")).toBe("*.csv");
    expect(patternForFormat("", "csv")).toBe("*.csv");
    expect(patternForFormat("sites/*.csv", "yaml")).toBe("sites/*.csv");
  });
});
