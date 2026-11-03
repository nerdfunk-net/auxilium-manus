import { describe, expect, it } from "vitest";

import {
  credentialInputs,
  deviceInputsInUse,
  suggestedDevicesInput,
  textInputs,
} from "./ai-release-inputs";

const INPUTS = [
  { name: "devs", type: "string" },
  { name: "note", type: "string" },
  { name: "cred", type: "reference", ref_kind: "credential" },
  { name: "inv", type: "reference", ref_kind: "inventory" },
  { name: "pw", type: "secret" },
];

const reader = (param: unknown, disabled = false, kind = "get-from-user") => ({
  id: "n",
  type: "workflowNode",
  data: { kind, disabled, pluginConfig: { device_param: param } },
});

describe("ai release inputs", () => {
  it("separates text inputs from credential references", () => {
    expect(textInputs(INPUTS).map((i) => i.name)).toEqual(["devs", "note"]);
    expect(credentialInputs(INPUTS).map((i) => i.name)).toEqual(["cred"]);
    expect(textInputs(null)).toEqual([]);
  });

  it("finds the inputs enabled Get from User steps read", () => {
    expect(
      deviceInputsInUse([
        reader("devs"),
        reader("off", true),
        reader("other", false, "send-commands"),
        reader(42),
        reader(""),
      ]),
    ).toEqual(["devs"]);
  });

  it("suggests the input only when exactly one text input is read", () => {
    expect(suggestedDevicesInput([reader("devs")], INPUTS)).toBe("devs");
    expect(
      suggestedDevicesInput([reader("devs"), reader("note")], INPUTS),
    ).toBeNull();
    expect(suggestedDevicesInput([reader("missing")], INPUTS)).toBeNull();
    expect(suggestedDevicesInput([], INPUTS)).toBeNull();
  });
});
