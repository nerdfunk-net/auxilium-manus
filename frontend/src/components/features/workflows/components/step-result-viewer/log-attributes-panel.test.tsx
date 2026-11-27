import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  LOG_ATTRIBUTES_METADATA_SUFFIX,
  LogAttributesPanel,
  extractLogAttributes,
} from "./log-attributes-panel";

const ENTRY = {
  output_destination: "stdout",
  output_format: "json",
  device_count: 2,
  content: '{\n  "devices": {}\n}',
};

describe("extractLogAttributes", () => {
  it("returns the entries under the suffix that carry the rendered content", () => {
    const entries = extractLogAttributes({
      [`log_1${LOG_ATTRIBUTES_METADATA_SUFFIX}`]: ENTRY,
      [`log_2${LOG_ATTRIBUTES_METADATA_SUFFIX}`]: { nope: true },
      other: ENTRY,
    });
    expect(entries).toEqual([ENTRY]);
  });

  it("ignores an entry that only has a raw snapshot (W4-15: content is the stored copy)", () => {
    const entries = extractLogAttributes({
      [`log_1${LOG_ATTRIBUTES_METADATA_SUFFIX}`]: { snapshot: { devices: {} } },
    });
    expect(entries).toEqual([]);
  });
});

describe("LogAttributesPanel", () => {
  it("shows the rendered content and the device count", () => {
    render(<LogAttributesPanel entries={[ENTRY]} />);
    expect(screen.getByText("2 devices")).toBeTruthy();
    expect(screen.getByText(/"devices": \{\}/)).toBeTruthy();
  });
});
