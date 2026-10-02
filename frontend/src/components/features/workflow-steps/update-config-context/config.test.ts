import { describe, expect, it } from "vitest";

import {
  addUpdateEntry,
  buildUpdateConfigContextConfig,
  emptyUpdateEntry,
  parseUpdateConfigContextConfig,
  patchUpdateEntry,
  removeUpdateEntry,
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

describe("updates parsing", () => {
  it("defaults to one empty row", () => {
    expect(parseUpdateConfigContextConfig({}).updates).toEqual([emptyUpdateEntry()]);
  });

  it.each([null, "tacacs", 5, {}, []])("falls back to one empty row for %j", (raw) => {
    expect(parseUpdateConfigContextConfig({ updates: raw }).updates).toEqual([emptyUpdateEntry()]);
  });

  it("keeps every entry in order and coerces malformed ones", () => {
    const { updates } = parseUpdateConfigContextConfig({
      updates: [
        { path: "tacacs.key", value_source: { type: "attribute", attribute_path: "custom.k" } },
        { path: "tacacs.level", value_source: { type: "template", template_id: "7" } },
        "junk",
      ],
    });
    expect(updates).toHaveLength(3);
    expect(updates[0]).toEqual({
      path: "tacacs.key",
      value_source: { type: "attribute", attribute_path: "custom.k", template_id: null },
    });
    expect(updates[1].value_source).toEqual({
      type: "template",
      attribute_path: "",
      template_id: 7,
    });
    expect(updates[2]).toEqual(emptyUpdateEntry());
  });

  it("keeps updates when another field is edited", () => {
    const updates = [{ path: "a", value_source: emptyUpdateEntry().value_source }];
    const saved = buildUpdateConfigContextConfig({ mode: "update", updates }, { mode: "append" });
    expect(saved.updates).toEqual(updates);
  });
});

describe("update entry helpers", () => {
  const first = { ...emptyUpdateEntry(), path: "a" };
  const second = { ...emptyUpdateEntry(), path: "b" };

  it("adds an empty row without mutating the input", () => {
    const input = [first];
    const next = addUpdateEntry(input);
    expect(next).toEqual([first, emptyUpdateEntry()]);
    expect(input).toEqual([first]);
  });

  it("removes the row at the index", () => {
    expect(removeUpdateEntry([first, second], 0)).toEqual([second]);
  });

  it("never removes the last row", () => {
    expect(removeUpdateEntry([first], 0)).toEqual([emptyUpdateEntry()]);
  });

  it("patches only the targeted row", () => {
    const input = [first, second];
    const next = patchUpdateEntry(input, 1, { path: "changed" });
    expect(next[0]).toBe(first);
    expect(next[1].path).toBe("changed");
    expect(input[1].path).toBe("b");
  });
});
