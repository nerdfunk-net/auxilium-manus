import { describe, expect, it } from "vitest";

import type { PaletteGroup, PaletteItem } from "./step-catalog";
import { ALL_CATEGORY_KEY } from "./step-library-filter";
import { buildStepSections } from "./step-library-sections";

function item(kind: string, category: string): PaletteItem {
  return { kind, title: kind, paletteCategory: category } as PaletteItem;
}

const GROUPS: PaletteGroup[] = [
  { categoryKey: "batfish", label: "Batfish", items: [item("batfish-init-snapshot", "batfish")] },
  {
    categoryKey: "nautobot",
    label: "Nautobot",
    items: [
      item("start-nautobot-job", "nautobot"),
      item("add-ip-to-nautobot", "nautobot"),
      item("get-nautobot-devices", "nautobot"),
      item("check-nautobot-job", "nautobot"),
      item("get-next-free-ip", "nautobot"),
    ],
  },
  {
    categoryKey: "cisco",
    label: "Cisco",
    items: [
      item("add-to-ise", "cisco"),
      item("get-catalyst-center-health", "cisco"),
      item("parse-cisco-config", "cisco"),
      item("get-ise-devices", "cisco"),
    ],
  },
];

describe("buildStepSections", () => {
  it("splits a category with sub-groups into ISE / Catalyst Center / Other sections", () => {
    const sections = buildStepSections(GROUPS, "cisco");
    expect(sections.map((s) => s.label)).toEqual(["ISE", "Catalyst Center", "Other"]);
    expect(sections[0].items.map((i) => i.kind)).toEqual(["add-to-ise", "get-ise-devices"]);
    expect(sections[2].items.map((i) => i.kind)).toEqual(["parse-cisco-config"]);
  });

  it("splits the Nautobot category into DCIM / IPAM / JOBS sections", () => {
    const sections = buildStepSections(GROUPS, "nautobot");
    expect(sections.map((s) => s.label)).toEqual(["DCIM", "IPAM", "JOBS"]);
    expect(sections[0].items.map((i) => i.kind)).toEqual(["get-nautobot-devices"]);
    expect(sections[1].items.map((i) => i.kind)).toEqual(["add-ip-to-nautobot", "get-next-free-ip"]);
    expect(sections[2].items.map((i) => i.kind)).toEqual(["start-nautobot-job", "check-nautobot-job"]);
  });

  it("omits empty sub-groups", () => {
    const only: PaletteGroup[] = [{ ...GROUPS[2], items: [item("add-to-ise", "cisco")] }];
    expect(buildStepSections(only, "cisco").map((s) => s.label)).toEqual(["ISE"]);
  });

  it("uses a header-less section for a category without sub-groups", () => {
    const sections = buildStepSections(GROUPS, "batfish");
    expect(sections).toHaveLength(1);
    expect(sections[0].label).toBeNull();
  });

  it("labels sections by category (and sub-group) in the All view", () => {
    expect(buildStepSections(GROUPS, ALL_CATEGORY_KEY).map((s) => s.label)).toEqual([
      "Batfish",
      "Nautobot · DCIM",
      "Nautobot · IPAM",
      "Nautobot · JOBS",
      "Cisco · ISE",
      "Cisco · Catalyst Center",
      "Cisco · Other",
    ]);
  });

  it("returns nothing for an unknown category", () => {
    expect(buildStepSections(GROUPS, "missing")).toEqual([]);
  });
});
