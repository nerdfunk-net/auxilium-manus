import { describe, expect, it } from "vitest";

import {
  getComparisonDiffEntries,
  getComparisonResultEntries,
  getContentMatchEntries,
  getMembershipEntries,
} from "./parsed-guards";

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

  it("finds the entry nested under its own node id (the current backend shape)", () => {
    // compare-data's mismatch branch always writes a sibling "comparison"
    // result entry alongside "comparison_diff" in the same node-id bag —
    // include it here too, since a lone { comparison_diff: <diff entry> }
    // bag is structurally indistinguishable from a one-feature
    // compare-pyats-snapshot feature map.
    const entries = getComparisonDiffEntries({
      "compare-data-1": {
        comparison: { kind: "comparison_result", matched: false, step_node_id: "compare-data-1" },
        comparison_diff: diffEntry(),
      },
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("compare-data-1.comparison_diff");
  });
});

describe("getComparisonResultEntries", () => {
  it("finds a comparison result nested under its own node id", () => {
    const entries = getComparisonResultEntries({
      "compare-data-1": {
        comparison: { kind: "comparison_result", matched: true, step_node_id: "compare-data-1" },
      },
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("compare-data-1.comparison");
    expect(entries[0].entry.matched).toBe(true);
  });
});

describe("getContentMatchEntries", () => {
  it("finds route-on-content's result nested under its own node id", () => {
    const entries = getContentMatchEntries({
      "route-on-content-3": {
        content_match: {
          kind: "content_match_result",
          matched: true,
          content_source: "running_config",
          match_mode: "regex",
          case_sensitive: false,
          multiline: false,
          matched_text: "access-class MGMT_in in",
        },
      },
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("route-on-content-3.content_match");
    expect(entries[0].entry.matched_text).toBe("access-class MGMT_in in");
  });
});

describe("getMembershipEntries", () => {
  it("finds list-contains's result nested under its own node id", () => {
    const entries = getMembershipEntries({
      "list-contains-2": {
        membership: {
          kind: "membership_result",
          matched: false,
          list_path: "parsed.cisco_config.running.access_lists",
          field: "name",
          value: "MGMT_in",
        },
      },
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].key).toBe("list-contains-2.membership");
    expect(entries[0].entry.matched).toBe(false);
  });
});
