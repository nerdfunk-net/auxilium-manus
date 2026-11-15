import { describe, expect, it } from "vitest";

import {
  buildGetFromAgentConfig,
  configProblems,
  parseGetFromAgentConfig,
} from "./config";

const VALID = {
  agent_source_id: "inv",
  handler: "list_devices",
  attributes: [{ name: "site", value: "berlin" }],
};

describe("parseGetFromAgentConfig", () => {
  it("fills defaults for an empty blob", () => {
    const parsed = parseGetFromAgentConfig({});
    expect(parsed).toMatchObject({
      agent_source_id: "",
      handler: "",
      attributes: [],
      timeout_seconds: 30,
    });
    expect(parsed.fan_out.enabled).toBe(false);
  });

  it("ignores malformed attribute rows and stringifies values", () => {
    const parsed = parseGetFromAgentConfig({
      attributes: [null, "x", { name: "n", value: 5 }, { name: 3 }],
    });
    expect(parsed.attributes).toEqual([
      { name: "n", value: "5" },
      { name: "", value: "" },
    ]);
  });
});

describe("buildGetFromAgentConfig", () => {
  it("keeps unknown keys and applies the patch", () => {
    const built = buildGetFromAgentConfig({ extra: 1, ...VALID }, { handler: "other" });
    expect(built.extra).toBe(1);
    expect(built.handler).toBe("other");
    expect(built.agent_source_id).toBe("inv");
  });
});

describe("configProblems", () => {
  it("accepts a valid configuration", () => {
    expect(configProblems(parseGetFromAgentConfig(VALID))).toEqual([]);
  });

  it("reports missing agent and handler", () => {
    const problems = configProblems(parseGetFromAgentConfig({}));
    expect(problems).toContain("Choose an agent.");
    expect(problems).toContain("Handler is required.");
  });

  it("rejects a bad handler name", () => {
    expect(configProblems(parseGetFromAgentConfig({ ...VALID, handler: "1bad" }))).toContain(
      "Handler may only contain letters, digits, '_', '.' and '-'.",
    );
  });

  it("rejects bad, secret-looking and duplicate attribute names", () => {
    const bad = (attributes: unknown[]) =>
      configProblems(parseGetFromAgentConfig({ ...VALID, attributes })).join(" ");
    expect(bad([{ name: "a.b", value: "x" }])).toMatch(/plain names/);
    expect(bad([{ name: "api_token", value: "x" }])).toMatch(/secrets/);
    expect(
      bad([
        { name: "a", value: "1" },
        { name: "a", value: "2" },
      ]),
    ).toMatch(/unique/);
  });

  it("uses the backend secret-name rule", () => {
    const flagged = (name: string) =>
      configProblems(parseGetFromAgentConfig({ ...VALID, attributes: [{ name, value: "x" }] })).some(
        (problem) => /secrets/.test(problem),
      );
    for (const name of ["community", "snmp_community", "passphrase", "wifi_psk", "auth_key", "db_pw"]) {
      expect(flagged(name)).toBe(true);
    }
    for (const name of ["credential", "my_credential", "password_hint", "site"]) {
      expect(flagged(name)).toBe(false);
    }
  });

  it("rejects over-long values and partial run input references", () => {
    const problems = (value: string) =>
      configProblems(
        parseGetFromAgentConfig({ ...VALID, attributes: [{ name: "a", value }] }),
      ).join(" ");
    expect(problems("x".repeat(4097))).toMatch(/4096/);
    expect(problems("{run_input.site.region}")).toMatch(/whole value/);
    expect(problems("{run_input.site}")).toBe("");
  });

  it("ignores untouched rows", () => {
    expect(
      configProblems(parseGetFromAgentConfig({ ...VALID, attributes: [{ name: "", value: "" }] })),
    ).toEqual([]);
  });

  it("rejects an out-of-range timeout", () => {
    expect(
      configProblems(parseGetFromAgentConfig({ ...VALID, timeout_seconds: 0 })).join(" "),
    ).toMatch(/Timeout/);
  });
});
