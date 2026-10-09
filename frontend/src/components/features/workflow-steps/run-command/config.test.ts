import { describe, expect, it } from "vitest";

import {
  buildRunCommandConfig,
  clampReadTimeout,
  DEFAULT_READ_TIMEOUT,
  MAX_READ_TIMEOUT,
  MIN_READ_TIMEOUT,
} from "./config";

describe("clampReadTimeout", () => {
  it("clamps into [MIN, MAX] and falls back for non-numbers", () => {
    expect(clampReadTimeout("1")).toBe(MIN_READ_TIMEOUT);
    expect(clampReadTimeout("99999")).toBe(MAX_READ_TIMEOUT);
    expect(clampReadTimeout("120")).toBe(120);
    expect(clampReadTimeout("abc")).toBe(DEFAULT_READ_TIMEOUT);
  });
});

describe("buildRunCommandConfig parser locking", () => {
  it("forces parser to none in config_mode", () => {
    const built = buildRunCommandConfig({}, { execution_mode: "config_mode", parser: "textfsm" });
    expect(built.parser).toBe("none");
  });

  it("forces parser to none when auto_confirm_prompts is on", () => {
    const built = buildRunCommandConfig({}, { auto_confirm_prompts: true, parser: "genie" });
    expect(built.parser).toBe("none");
  });

  it("keeps the parser in plain exec mode", () => {
    expect(buildRunCommandConfig({}, { parser: "textfsm" }).parser).toBe("textfsm");
  });

  it("drops write_config_after_execution outside config_mode", () => {
    const built = buildRunCommandConfig({}, { write_config_after_execution: true });
    expect(built.write_config_after_execution).toBe(false);
  });
});
