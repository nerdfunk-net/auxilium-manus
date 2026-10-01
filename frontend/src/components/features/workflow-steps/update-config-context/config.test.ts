import { describe, expect, it } from "vitest";

import {
  buildUpdateConfigContextConfig,
  parseUpdateConfigContextConfig,
  toLocalConfigContextPath,
} from "./config";

describe("toLocalConfigContextPath", () => {
  it("strips the merged config_context attribute prefix", () => {
    expect(toLocalConfigContextPath("nautobot.config_context.tacacs")).toBe("tacacs");
    expect(toLocalConfigContextPath("nautobot.config_context.tacacs[address=1.2.3.4].key")).toBe(
      "tacacs[address=1.2.3.4].key",
    );
  });

  it("strips the local_config_context_data attribute prefix", () => {
    expect(toLocalConfigContextPath("nautobot.local_config_context_data.credentials.0.password")).toBe(
      "credentials.0.password",
    );
  });

  it("leaves paths outside a config context unchanged", () => {
    expect(toLocalConfigContextPath("tacacs.key")).toBe("tacacs.key");
    expect(toLocalConfigContextPath("nautobot.role.name")).toBe("nautobot.role.name");
  });

  it("returns an empty path when only the prefix itself is picked", () => {
    expect(toLocalConfigContextPath("nautobot.config_context")).toBe("");
  });
});

describe("create_local_if_missing parsing", () => {
  it("defaults to false", () => {
    expect(parseUpdateConfigContextConfig({}).create_local_if_missing).toBe(false);
  });

  it.each([true, "true", "TRUE", "yes", "1", "on"])("treats %j as on, like the executor", (raw) => {
    expect(parseUpdateConfigContextConfig({ create_local_if_missing: raw }).create_local_if_missing).toBe(
      true,
    );
  });

  it.each([false, "false", "no", "0", "off", "", null, 0])("treats %j as off", (raw) => {
    expect(parseUpdateConfigContextConfig({ create_local_if_missing: raw }).create_local_if_missing).toBe(
      false,
    );
  });

  it("keeps the option on when another field is edited", () => {
    const saved = buildUpdateConfigContextConfig(
      { create_local_if_missing: "true", mode: "update" },
      { path: "tacacs" },
    );
    expect(saved.create_local_if_missing).toBe(true);
  });
});
