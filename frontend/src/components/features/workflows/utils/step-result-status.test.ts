import { describe, expect, it } from "vitest";

import type { WorkflowStepResult } from "../types/workflow-runs";
import {
  countOutcomeDevices,
  deriveStepDisplayStatus,
  detectRunFanOut,
  summarizeCompareData,
  summarizeFanIn,
  summarizeFanOutInventory,
  summarizeLogAttributes,
  summarizeLogMessage,
  summarizeRenderJinjaTemplate,
  summarizeRouteCounts,
} from "./step-result-status";

type Output = Record<string, unknown>;

function context(deviceIds: string[] = [], metadata: Output = {}): Output {
  return {
    devices: Object.fromEntries(deviceIds.map((id) => [id, {}])),
    metadata,
  };
}

/** Build a step-output envelope: `{ outcomes: { <name>: context } }`. */
function envelope(outcomes: Record<string, Output>): Output {
  return { outcomes };
}

function withMetadata(metadata: Output): Output {
  return envelope({ success: context(["d1"], metadata) });
}

describe("deriveStepDisplayStatus", () => {
  it.each(["pending", "running", "skipped"] as const)(
    "passes %s through without looking at the output",
    (status) => {
      const failing = envelope({ failure: context(["d1"]) });
      expect(deriveStepDisplayStatus(status, failing)).toBe(status);
    },
  );

  it("keeps an engine failure as failed even when devices succeeded", () => {
    expect(deriveStepDisplayStatus("failed", envelope({ success: context(["d1"]) }))).toBe(
      "failed",
    );
  });

  it("falls back to the engine status when the output is not an envelope", () => {
    expect(deriveStepDisplayStatus("success", null)).toBe("success");
    expect(deriveStepDisplayStatus("success", { foo: 1 })).toBe("success");
  });

  it("is partial when both success and failure devices exist", () => {
    const output = envelope({ success: context(["a"]), failure: context(["b"]) });
    expect(deriveStepDisplayStatus("success", output)).toBe("partial");
  });

  it("is failed when only failure devices exist, even if the engine said success", () => {
    expect(deriveStepDisplayStatus("success", envelope({ failure: context(["b"]) }))).toBe(
      "failed",
    );
  });

  it("is success for success devices only, or for an empty envelope", () => {
    expect(deriveStepDisplayStatus("success", envelope({ success: context(["a"]) }))).toBe(
      "success",
    );
    expect(deriveStepDisplayStatus("success", envelope({}))).toBe("success");
  });

  it("keeps an engine 'partial' when the devices do not contradict it", () => {
    expect(deriveStepDisplayStatus("partial", envelope({ success: context(["a"]) }))).toBe(
      "partial",
    );
  });

  it("ignores outcomes with zero devices", () => {
    const output = envelope({ success: context(["a"]), failure: context([]) });
    expect(deriveStepDisplayStatus("success", output)).toBe("success");
  });
});

describe("countOutcomeDevices", () => {
  it("counts devices per outcome and the number of outcomes", () => {
    const output = envelope({
      success: context(["a", "b"]),
      failure: context(["c"]),
      custom: context([]),
    });
    expect(countOutcomeDevices(output)).toEqual({ success: 2, failure: 1, totalOutcomes: 3 });
  });

  it("returns zeros for missing or non-envelope output", () => {
    const zero = { success: 0, failure: 0, totalOutcomes: 0 };
    expect(countOutcomeDevices(null)).toEqual(zero);
    expect(countOutcomeDevices({})).toEqual(zero);
    expect(countOutcomeDevices(envelope({}))).toEqual(zero);
  });
});

describe("summarizeRouteCounts", () => {
  it("lists only outcomes with devices routed", () => {
    const out = withMetadata({ "n1.routed_counts": { yes: 3, no: 0, maybe: 1 } });
    expect(summarizeRouteCounts(out)).toBe("yes: 3 · maybe: 1");
  });

  it("says no devices were routed when every count is zero or non-numeric", () => {
    expect(summarizeRouteCounts(withMetadata({ "n1.routed_counts": { yes: 0, no: "2" } }))).toBe(
      "no devices routed",
    );
  });

  it.each([[null], [{}], [withMetadata({})], [withMetadata({ "n1.routed_counts": "x" })]])(
    "returns null when there is nothing to summarize (%j)",
    (out) => {
      expect(summarizeRouteCounts(out as Output | null)).toBeNull();
    },
  );
});

describe("summarizeLogMessage", () => {
  it("returns the trimmed message", () => {
    const out = withMetadata({ "n1.debug_logs": { message: "  hello  " } });
    expect(summarizeLogMessage(out)).toBe("hello");
  });

  it.each([[{ message: "   " }], [{ message: 5 }], [{}], ["text"]])(
    "returns null for debug_logs %j",
    (debugLogs) => {
      expect(summarizeLogMessage(withMetadata({ "n1.debug_logs": debugLogs }))).toBeNull();
    },
  );
});

describe("summarizeLogAttributes", () => {
  it("defaults to STDOUT and JSON", () => {
    expect(summarizeLogAttributes(withMetadata({ "n1.log_attributes": {} }))).toBe(
      "STDOUT · JSON",
    );
  });

  it("pluralises the device count", () => {
    const one = withMetadata({ "n1.log_attributes": { device_count: 1 } });
    const many = withMetadata({ "n1.log_attributes": { device_count: 2 } });
    const zero = withMetadata({ "n1.log_attributes": { device_count: 0 } });
    expect(summarizeLogAttributes(one)).toBe("STDOUT · JSON · 1 device");
    expect(summarizeLogAttributes(many)).toBe("STDOUT · JSON · 2 devices");
    expect(summarizeLogAttributes(zero)).toBe("STDOUT · JSON · 0 devices");
  });

  it("shows file destination, pretty text and the file path", () => {
    const out = withMetadata({
      "n1.log_attributes": {
        output_destination: "file",
        output_format: "pretty_text",
        device_count: 3,
        file_path: "/tmp/out.txt",
      },
    });
    expect(summarizeLogAttributes(out)).toBe("file · pretty text · 3 devices · /tmp/out.txt");
  });

  it("does not show a file path for STDOUT output", () => {
    const out = withMetadata({ "n1.log_attributes": { file_path: "/tmp/x" } });
    expect(summarizeLogAttributes(out)).toBe("STDOUT · JSON");
  });

  it("returns null without log_attributes", () => {
    expect(summarizeLogAttributes(withMetadata({}))).toBeNull();
  });
});

describe("fan-out", () => {
  const fanOut = (config: Output, deviceIds: string[]) =>
    envelope({ success: context(deviceIds, { _fan_out: config }) });

  describe("summarizeFanOutInventory", () => {
    it("describes per-device fan-out with one child per device", () => {
      const out = fanOut({ enabled: true, mode: "per_device" }, ["a", "b", "c"]);
      expect(summarizeFanOutInventory(out)).toBe("Fan-out: 3 children · per device");
    });

    it("uses the singular for exactly one child", () => {
      const out = fanOut({ enabled: true }, ["a"]);
      expect(summarizeFanOutInventory(out)).toBe("Fan-out: 1 child · per device");
    });

    it("rounds up the child count in chunked mode and shows the concurrency cap", () => {
      const out = fanOut(
        { enabled: true, mode: "chunked", chunk_size: 2, max_concurrency: 4 },
        ["a", "b", "c", "d", "e"],
      );
      expect(summarizeFanOutInventory(out)).toBe(
        "Fan-out: 3 children · chunked (2/child) · max 4 concurrent",
      );
    });

    it.each([[0], [-5]])("clamps chunk_size %j to 1", (chunk_size) => {
      const out = fanOut({ enabled: true, mode: "chunked", chunk_size }, ["a", "b"]);
      expect(summarizeFanOutInventory(out)).toContain("chunked (1/child)");
      expect(summarizeFanOutInventory(out)).toContain("2 children");
    });

    it("treats an unknown mode as per-device", () => {
      expect(summarizeFanOutInventory(fanOut({ enabled: true, mode: "weird" }, ["a"]))).toContain(
        "per device",
      );
    });

    it("has zero children for an empty chunked inventory", () => {
      const out = fanOut({ enabled: true, mode: "chunked", chunk_size: 3 }, []);
      expect(summarizeFanOutInventory(out)).toContain("0 children");
    });

    it.each([[undefined], [{ enabled: false }], ["yes"], [null]])(
      "returns null when fan-out is not enabled (%j)",
      (config) => {
        expect(summarizeFanOutInventory(fanOut(config as Output, ["a"]))).toBeNull();
      },
    );

    it("returns null for non-envelope output or an envelope with no outcomes", () => {
      expect(summarizeFanOutInventory(null)).toBeNull();
      expect(summarizeFanOutInventory(envelope({}))).toBeNull();
    });
  });

  describe("detectRunFanOut", () => {
    const step = (step_type: string, output: Output | null): WorkflowStepResult =>
      ({ step_type, output }) as unknown as WorkflowStepResult;

    it("finds the config on the first inventory step that has fan-out enabled", () => {
      const info = detectRunFanOut([
        step("run-command", fanOut({ enabled: true }, ["a"])),
        step("get-nautobot-devices", fanOut({ enabled: false }, ["a"])),
        step("get-git-devices", fanOut({ enabled: true, mode: "chunked", chunk_size: 2 }, ["a", "b", "c"])),
      ]);
      expect(info).toEqual({
        mode: "chunked",
        chunkSize: 2,
        maxConcurrency: 0,
        deviceCount: 3,
        childCount: 2,
      });
    });

    it("only looks at inventory step types", () => {
      expect(detectRunFanOut([step("run-command", fanOut({ enabled: true }, ["a"]))])).toBeNull();
    });

    it("returns null for no steps", () => {
      expect(detectRunFanOut([])).toBeNull();
      expect(detectRunFanOut([step("get-nautobot-devices", null)])).toBeNull();
    });
  });

  describe("summarizeFanIn", () => {
    it("reports the merged device count with correct pluralisation", () => {
      expect(summarizeFanIn(withMetadata({ "n.fan_in": { device_count: 1 } }))).toBe(
        "Merged 1 device from fan-out children",
      );
      expect(summarizeFanIn(withMetadata({ "n.fan_in": { device_count: 4 } }))).toBe(
        "Merged 4 devices from fan-out children",
      );
      expect(summarizeFanIn(withMetadata({ "n.fan_in": { device_count: 0 } }))).toBe(
        "Merged 0 devices from fan-out children",
      );
    });

    it.each([[{}], [{ device_count: "3" }], ["x"], [null]])(
      "returns null for fan_in %j",
      (value) => {
        expect(summarizeFanIn(withMetadata({ "n.fan_in": value }))).toBeNull();
      },
    );

    it("returns null without a fan_in entry", () => {
      expect(summarizeFanIn(withMetadata({}))).toBeNull();
      expect(summarizeFanIn(null)).toBeNull();
    });
  });
});

describe("summarizeRenderJinjaTemplate", () => {
  it("shows the rendered count, failures and output key", () => {
    const out = withMetadata({
      "tpl.rendered_success_count": 5,
      "tpl.rendered_failure_count": 2,
      "tpl.rendered_template_key": "config",
    });
    expect(summarizeRenderJinjaTemplate(out)).toBe("5 rendered · 2 failed → config");
  });

  it("omits the failure part when there are none and the key part when empty", () => {
    const out = withMetadata({
      "tpl.rendered_success_count": 5,
      "tpl.rendered_failure_count": 0,
      "tpl.rendered_template_key": "",
    });
    expect(summarizeRenderJinjaTemplate(out)).toBe("5 rendered");
  });

  it("uses the failure count of the same node prefix", () => {
    const out = withMetadata({
      "a.rendered_success_count": 1,
      "b.rendered_failure_count": 9,
    });
    expect(summarizeRenderJinjaTemplate(out)).toBe("1 rendered");
  });

  it("returns null when the success count is missing or not a number", () => {
    expect(summarizeRenderJinjaTemplate(withMetadata({}))).toBeNull();
    expect(
      summarizeRenderJinjaTemplate(withMetadata({ "t.rendered_success_count": "5" })),
    ).toBeNull();
  });
});

describe("summarizeCompareData", () => {
  it("lists the non-zero counts", () => {
    const out = withMetadata({ "c.comparison_counts": { match: 3, mismatch: 1, failure: 2 } });
    expect(summarizeCompareData(out)).toBe("3 match · 1 mismatch · 2 failed");
  });

  it("skips zero and non-numeric counts", () => {
    const out = withMetadata({ "c.comparison_counts": { match: 0, mismatch: "1", failure: 2 } });
    expect(summarizeCompareData(out)).toBe("2 failed");
  });

  it("says no devices were compared when all counts are empty", () => {
    expect(summarizeCompareData(withMetadata({ "c.comparison_counts": {} }))).toBe(
      "no devices compared",
    );
  });

  it.each([["x"], [null]])("returns null for counts %j", (counts) => {
    expect(summarizeCompareData(withMetadata({ "c.comparison_counts": counts }))).toBeNull();
  });

  it("returns null without comparison_counts", () => {
    expect(summarizeCompareData(withMetadata({}))).toBeNull();
  });
});

describe("malformed envelopes", () => {
  // `isStepOutcomeEnvelope` only checks that `outcomes` is an object, so a
  // corrupted or truncated stored result reaches these helpers. The run list
  // should degrade, not crash the page.
  // KNOWN BUG: both throw a TypeError today. Remove `.fails` once fixed.
  it.fails("deriveStepDisplayStatus tolerates an outcome without devices", () => {
    expect(() =>
      deriveStepDisplayStatus("success", { outcomes: { success: { metadata: {} } } }),
    ).not.toThrow();
  });

  it.fails("summarizers tolerate an outcome without metadata", () => {
    const out = { outcomes: { success: { devices: {} } } };
    expect(() => summarizeRouteCounts(out)).not.toThrow();
    expect(() => summarizeFanOutInventory(out)).not.toThrow();
    expect(() => summarizeFanIn(out)).not.toThrow();
  });
});
