import { describe, expect, it } from "vitest";

import { getComparisonDiffEntries } from "./parsed-guards";

const artifactRef = {
  artifact_id: "a1",
  kind: "comparison_diff",
  media_type: "text/plain",
  size_bytes: 10,
  sha256: null,
  created_at: "2026-01-01T00:00:00Z",
};

function diffEntry(overrides: Record<string, unknown> = {}) {
  return {
    kind: "comparison_diff",
    matched: false,
    artifact_ref: artifactRef,
    step_node_id: "n1",
    ...overrides,
  };
}

describe("getComparisonDiffEntries", () => {
  it("reads the flat single-entry shape (compare-data)", () => {
    const entries = getComparisonDiffEntries({
      "compare-data-1.comparison_diff": diffEntry(),
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("compare-data-1.comparison_diff");
  });

  it("unwraps the { feature: entry } map shape (compare-pyats-snapshot)", () => {
    const entries = getComparisonDiffEntries({
      "compare-pyats-snapshot-4.comparison_diff": {
        routing: diffEntry({
          feature: "routing",
          live_snapshot_ref: { ...artifactRef, artifact_id: "live" },
          reference_snapshot_ref: { ...artifactRef, artifact_id: "ref" },
        }),
        bgp: diffEntry({ feature: "bgp" }),
      },
    });

    expect(entries.map((e) => e.key)).toEqual([
      "compare-pyats-snapshot-4.comparison_diff · routing",
      "compare-pyats-snapshot-4.comparison_diff · bgp",
    ]);
    expect(entries[0].entry.live_snapshot_ref?.artifact_id).toBe("live");
    expect(entries[0].entry.reference_snapshot_ref?.artifact_id).toBe("ref");
  });

  it("ignores unrelated parsed keys", () => {
    const entries = getComparisonDiffEntries({
      "some-step.comparison": { kind: "comparison_result", matched: true },
      "run-command-1.parsed": { "show version": { parsed: {}, error: null } },
    });

    expect(entries).toHaveLength(0);
  });
});
