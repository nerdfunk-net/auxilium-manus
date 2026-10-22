import { describe, expect, it } from "vitest";

import {
  buildRouteToAgentConfig,
  configProblems,
  formatLines,
  parseLines,
  parseParamsText,
  parseRouteToAgentConfig,
} from "./config";

const VALID = {
  agent_source_id: "geo",
  handler: "resolve_location",
  params: { strict: true },
  input_paths: ["nautobot.location.name"],
  content_inputs: [],
  destination_path: "agent.geo",
  output_keys: ["location"],
};

describe("parseRouteToAgentConfig", () => {
  it("fills defaults for an empty blob", () => {
    expect(parseRouteToAgentConfig({})).toEqual({
      agent_source_id: "",
      handler: "",
      params: {},
      input_paths: [],
      content_inputs: [],
      destination_path: "",
      output_keys: [],
      allow_missing_outputs: false,
      timeout_seconds: 30,
    });
  });

  it("ignores values of the wrong type", () => {
    const parsed = parseRouteToAgentConfig({
      agent_source_id: 5,
      params: "text",
      input_paths: "a",
      output_keys: [1, "ok", null],
      allow_missing_outputs: "yes",
      timeout_seconds: "soon",
    });
    expect(parsed.agent_source_id).toBe("");
    expect(parsed.params).toEqual({});
    expect(parsed.input_paths).toEqual([]);
    expect(parsed.output_keys).toEqual(["ok"]);
    expect(parsed.allow_missing_outputs).toBe(false);
    expect(parsed.timeout_seconds).toBe(30);
  });

  it("keeps a valid blob unchanged", () => {
    expect(parseRouteToAgentConfig(VALID)).toMatchObject(VALID);
  });
});

describe("buildRouteToAgentConfig", () => {
  it("merges a patch over normalised values and keeps unknown keys", () => {
    const built = buildRouteToAgentConfig({ ...VALID, extra: 1 }, { handler: "other" });
    expect(built.handler).toBe("other");
    expect(built.agent_source_id).toBe("geo");
    expect(built.extra).toBe(1);
    expect(built.timeout_seconds).toBe(30);
  });
});

describe("parseLines / formatLines", () => {
  it("splits on newlines and commas, trims, drops blanks and duplicates", () => {
    expect(parseLines("a.b\n c.d ,e\n\n a.b")).toEqual(["a.b", "c.d", "e"]);
    expect(parseLines("")).toEqual([]);
  });

  it("round-trips through formatLines", () => {
    expect(parseLines(formatLines(["x", "y"]))).toEqual(["x", "y"]);
  });
});

describe("parseParamsText", () => {
  it("accepts blank as an empty object and JSON objects", () => {
    expect(parseParamsText("  ")).toEqual({ ok: true, value: {} });
    expect(parseParamsText('{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });
  });

  it("rejects invalid JSON and non-objects", () => {
    expect(parseParamsText("{").ok).toBe(false);
    expect(parseParamsText("[1]").ok).toBe(false);
    expect(parseParamsText('"text"').ok).toBe(false);
    expect(parseParamsText("null").ok).toBe(false);
  });

  it("rejects params above 16 KiB", () => {
    const big = JSON.stringify({ blob: "x".repeat(17 * 1024) });
    expect(parseParamsText(big).ok).toBe(false);
  });
});

describe("configProblems", () => {
  const problems = (patch: Record<string, unknown>) =>
    configProblems(parseRouteToAgentConfig({ ...VALID, ...patch }));

  it("is empty for a valid configuration", () => {
    expect(problems({})).toEqual([]);
  });

  it("requires source, handler, destination and output keys", () => {
    const missing = configProblems(parseRouteToAgentConfig({ input_paths: ["a.b"] }));
    expect(missing.join(" ")).toMatch(/agent/i);
    expect(missing.join(" ")).toMatch(/handler/i);
    expect(missing.join(" ")).toMatch(/destination/i);
    expect(missing.join(" ")).toMatch(/output/i);
  });

  it("requires at least one input", () => {
    expect(problems({ input_paths: [], content_inputs: [] })).not.toEqual([]);
    expect(problems({ input_paths: [], content_inputs: ["running_config"] })).toEqual([]);
  });

  it("mirrors the backend handler and key rules", () => {
    expect(problems({ handler: "has space" })).not.toEqual([]);
    expect(problems({ handler: "../x" })).not.toEqual([]);
    expect(problems({ output_keys: ["a.b"] })).not.toEqual([]);
    expect(problems({ output_keys: ["ok_1", "also-ok"] })).toEqual([]);
  });

  it("rejects destinations that could rewrite the device", () => {
    for (const bad of ["device.name", "parsed.x", "run_input.x", "error.x", "name", "hostname.x", "agent"]) {
      expect(problems({ destination_path: bad }), bad).not.toEqual([]);
    }
    expect(problems({ destination_path: "agent.geo.result" })).toEqual([]);
  });

  it("bounds the timeout", () => {
    expect(problems({ timeout_seconds: 0 })).not.toEqual([]);
    expect(problems({ timeout_seconds: 601 })).not.toEqual([]);
    expect(problems({ timeout_seconds: 600 })).toEqual([]);
  });
});
