import { describe, expect, it } from "vitest";

import { isStepOutcomeEnvelope, parseStepOutput } from "./workflow-context-types";

const outcome = { devices: {}, metadata: {} };

describe("isStepOutcomeEnvelope", () => {
  it.each([
    [{ outcomes: {} }],
    [{ outcomes: { success: outcome } }],
    [{ outcomes: { success: outcome, failure: outcome }, extra: 1 }],
  ])("accepts %j", (value) => {
    expect(isStepOutcomeEnvelope(value)).toBe(true);
  });

  it.each([
    [null],
    [undefined],
    ["text"],
    [[]],
    [{}],
    [{ outcomes: null }],
    [{ outcomes: [] }],
    [{ outcomes: "x" }],
    [{ outcomes: { success: null } }],
    [{ outcomes: { success: "x" } }],
    [{ outcomes: { success: { metadata: {} } } }],
    [{ outcomes: { success: { devices: {} } } }],
    [{ outcomes: { success: { devices: [], metadata: {} } } }],
    [{ outcomes: { success: outcome, failure: { devices: {} } } }],
  ])("rejects %j", (value) => {
    expect(isStepOutcomeEnvelope(value)).toBe(false);
  });
});

describe("parseStepOutput", () => {
  it("returns the envelope itself or null", () => {
    const envelope = { outcomes: { success: outcome } };
    expect(parseStepOutput(envelope)).toBe(envelope);
    expect(parseStepOutput({ outcomes: { success: {} } })).toBeNull();
    expect(parseStepOutput(null)).toBeNull();
  });
});
