import { describe, expect, it } from "vitest";

import type { StaticAttributeDef } from "@/components/features/workflows/types/workflow-persistence";

import {
  MAX_WAIT_SECONDS,
  MIN_WAIT_SECONDS,
  analyseTarget,
  callerFansOut,
  cleanRunInputs,
  clampNumber,
  missingRequiredInputs,
  startWorkflowFromConfig,
} from "./start-workflow-config";

const fromUser = (param: string, extra: Record<string, unknown> = {}) => ({
  id: param,
  data: {
    kind: "get-from-user",
    pluginConfig: { device_param: param },
    ...extra,
  },
});

describe("startWorkflowFromConfig", () => {
  it("falls back to waiting five minutes and one run for all devices", () => {
    expect(startWorkflowFromConfig({})).toEqual({
      workflow_id: null,
      workflow_name: "",
      devices_input: "",
      run_mode: "all_devices",
      max_runs: 25,
      run_inputs: {},
      wait: true,
      wait_seconds: 300,
      poll_interval_seconds: 5,
      allow_partial: false,
    });
  });

  it("keeps wait off when it was switched off, also in string form", () => {
    expect(startWorkflowFromConfig({ wait: false }).wait).toBe(false);
    expect(startWorkflowFromConfig({ wait: "false" }).wait).toBe(false);
  });

  it("never exceeds the ten minute ceiling", () => {
    expect(startWorkflowFromConfig({ wait_seconds: 9999 }).wait_seconds).toBe(
      MAX_WAIT_SECONDS,
    );
    expect(startWorkflowFromConfig({ wait_seconds: 1 }).wait_seconds).toBe(
      MIN_WAIT_SECONDS,
    );
  });

  it("rejects a non-positive or non-numeric workflow id", () => {
    expect(startWorkflowFromConfig({ workflow_id: 0 }).workflow_id).toBeNull();
    expect(
      startWorkflowFromConfig({ workflow_id: "abc" }).workflow_id,
    ).toBeNull();
    expect(startWorkflowFromConfig({ workflow_id: "12" }).workflow_id).toBe(12);
  });

  it("only offers one run per device when there is an input to put the device in", () => {
    expect(startWorkflowFromConfig({ run_mode: "per_device" }).run_mode).toBe(
      "all_devices",
    );
    expect(
      startWorkflowFromConfig({
        run_mode: "per_device",
        devices_input: "targets",
      }).run_mode,
    ).toBe("per_device");
  });

  it("keeps the run cap in range", () => {
    expect(startWorkflowFromConfig({ max_runs: 0 }).max_runs).toBe(1);
    expect(startWorkflowFromConfig({ max_runs: 5000 }).max_runs).toBe(200);
  });
});

describe("clampNumber", () => {
  it("uses the fallback for NaN", () => {
    expect(clampNumber("x", 1, 10, 5)).toBe(5);
  });
});

describe("analyseTarget", () => {
  const attrs: StaticAttributeDef[] = [
    { name: "targets", type: "string", required: true },
    { name: "site", type: "string", required: false, default: "lab" },
    { name: "inv", type: "reference", ref_kind: "inventory", required: false },
    { name: "key", type: "secret", required: true },
  ];

  it("finds the text input an enabled Get from User step reads", () => {
    const result = analyseTarget([fromUser("targets")], attrs);
    expect(result.deviceInputs).toEqual(["targets"]);
    expect(result.otherAttributes.map((a) => a.name)).toEqual(["site", "inv"]);
    expect(result.secretNames).toEqual(["key"]);
  });

  it("ignores a disabled Get from User step", () => {
    expect(
      analyseTarget([fromUser("targets", { disabled: true })], attrs)
        .deviceInputs,
    ).toEqual([]);
  });

  it("only counts a text input", () => {
    const numeric: StaticAttributeDef[] = [
      { name: "targets", type: "number", required: false },
    ];
    expect(analyseTarget([fromUser("targets")], numeric).deviceInputs).toEqual(
      [],
    );
  });

  it("copes with a workflow without nodes or inputs", () => {
    expect(analyseTarget(null, undefined)).toEqual({
      deviceInputs: [],
      otherAttributes: [],
      secretNames: [],
    });
  });
});

describe("run inputs", () => {
  it("drops empty values so the default applies", () => {
    expect(
      cleanRunInputs({ a: "", b: "  ", c: 0, d: false, e: "x", f: Number.NaN }),
    ).toEqual({
      c: 0,
      d: false,
      e: "x",
    });
  });

  it("names required inputs without default or value", () => {
    const attrs: StaticAttributeDef[] = [
      { name: "a", type: "string", required: true },
      { name: "b", type: "string", required: true, default: "x" },
      { name: "c", type: "string", required: false },
      { name: "d", type: "number", required: true },
    ];
    expect(missingRequiredInputs(attrs, { d: 0 })).toEqual(["a"]);
    expect(missingRequiredInputs(attrs, {})).toEqual(["a", "d"]);
  });
});

describe("callerFansOut", () => {
  it("is true when any step of the calling workflow fans out", () => {
    expect(
      callerFansOut([
        { data: { pluginConfig: { fan_out: { enabled: true } } } },
      ]),
    ).toBe(true);
    expect(
      callerFansOut([
        { data: { pluginConfig: { fan_out: { enabled: false } } } },
      ]),
    ).toBe(false);
    expect(callerFansOut(undefined)).toBe(false);
  });
});
