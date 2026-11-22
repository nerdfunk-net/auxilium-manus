import { describe, expect, it } from "vitest";

import {
  buildUploadBinaryConfig,
  clampReadTimeout,
  hasWhitespace,
  isValidExpectedMd5,
} from "./upload-binary-config";

describe("buildUploadBinaryConfig", () => {
  it("fills defaults for an empty config", () => {
    expect(buildUploadBinaryConfig({})).toEqual({
      credential_reference: "",
      credential_source: "fixed",
      credential_param: "",
      destination_filename: "",
      file_system: "",
      overwrite: false,
      network_driver_override: "",
      socket_timeout: 10,
      git_repository_id: null,
      allow_stale_repository: false,
      source_path: "",
      expected_md5: "",
      read_timeout: 600,
    });
  });

  it("keeps the keys the Git source panel writes when another field is edited", () => {
    const next = buildUploadBinaryConfig(
      { git_repository_id: 7, allow_stale_repository: true, source_path: "a.bin" },
      { file_system: "flash:" },
    );
    expect(next.git_repository_id).toBe(7);
    expect(next.allow_stale_repository).toBe(true);
    expect(next.source_path).toBe("a.bin");
    expect(next.file_system).toBe("flash:");
  });

  it("never carries an inline_transfer key", () => {
    expect("inline_transfer" in buildUploadBinaryConfig({ inline_transfer: true })).toBe(false);
  });

  it("ignores values of the wrong type", () => {
    const next = buildUploadBinaryConfig({
      git_repository_id: "7",
      overwrite: "yes",
      socket_timeout: "30",
      credential_source: "other",
    });
    expect(next).toMatchObject({
      git_repository_id: null,
      overwrite: false,
      socket_timeout: 10,
      credential_source: "fixed",
    });
  });
});

describe("isValidExpectedMd5", () => {
  it("accepts empty and 32 hex characters, either case, trimmed", () => {
    expect(isValidExpectedMd5("")).toBe(true);
    expect(isValidExpectedMd5("  ")).toBe(true);
    expect(isValidExpectedMd5(` ${"aB".repeat(16)} `)).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isValidExpectedMd5("abc")).toBe(false);
    expect(isValidExpectedMd5("g".repeat(32))).toBe(false);
    expect(isValidExpectedMd5("a".repeat(33))).toBe(false);
  });
});

describe("clampReadTimeout", () => {
  it("keeps the value inside the backend bounds (5-600)", () => {
    expect(clampReadTimeout("120")).toBe(120);
    expect(clampReadTimeout("1")).toBe(5);
    expect(clampReadTimeout("9999")).toBe(600);
    expect(clampReadTimeout("")).toBe(5);
  });
});

describe("hasWhitespace", () => {
  it("flags spaces and line breaks inside a value, not around it", () => {
    expect(hasWhitespace("flash:")).toBe(false);
    expect(hasWhitespace("  flash: ")).toBe(false);
    expect(hasWhitespace("a b.bin")).toBe(true);
    expect(hasWhitespace("a.bin\nreload")).toBe(true);
  });
});
