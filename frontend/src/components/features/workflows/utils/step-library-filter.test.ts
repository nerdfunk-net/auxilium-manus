import { describe, expect, it } from "vitest";

import type { PaletteGroup, PaletteItem } from "./step-catalog";
import {
  filterAvailableGroups,
  filterGroupsByQuery,
} from "./step-library-filter";

function item(kind: string, category: string, overview = ""): PaletteItem {
  return {
    kind,
    title: kind.toUpperCase(),
    overview,
    description: "",
    paletteCategory: category,
    icon: (() => null) as unknown as PaletteItem["icon"],
  } as PaletteItem;
}

const GROUPS: PaletteGroup[] = [
  { categoryKey: "nautobot", label: "Nautobot", items: [item("get-devices", "nautobot", "inventory")] },
  { categoryKey: "pyats", label: "PyATS", items: [item("pyats-run", "pyats")] },
  { categoryKey: "batfish", label: "Batfish", items: [item("batfish-init", "batfish")] },
  {
    categoryKey: "secrets",
    label: "Secrets",
    items: [item("secret-get", "secrets"), item("encrypt-attribute", "secrets")],
  },
];

describe("filterAvailableGroups", () => {
  it("hides pyats, batfish and secret-manager steps when nothing is configured", () => {
    const result = filterAvailableGroups(GROUPS, {
      hasPyatsSource: false,
      hasBatfishSource: false,
      hasSecretManagerConnection: false,
    });
    expect(result.map((g) => g.categoryKey)).toEqual(["nautobot", "secrets"]);
    expect(result[1].items.map((i) => i.kind)).toEqual(["encrypt-attribute"]);
  });

  it("keeps everything when all sources are configured", () => {
    const result = filterAvailableGroups(GROUPS, {
      hasPyatsSource: true,
      hasBatfishSource: true,
      hasSecretManagerConnection: true,
    });
    expect(result).toEqual(GROUPS);
  });

  it("drops a group whose only steps were secret-manager steps", () => {
    const only = [{ categoryKey: "secrets", label: "Secrets", items: [item("secret-set", "secrets")] }];
    expect(
      filterAvailableGroups(only, {
        hasPyatsSource: true,
        hasBatfishSource: true,
        hasSecretManagerConnection: false,
      }),
    ).toEqual([]);
  });
});

describe("filterGroupsByQuery", () => {
  it("returns all groups for an empty query", () => {
    expect(filterGroupsByQuery(GROUPS, "  ")).toBe(GROUPS);
  });

  it("matches title, overview and kind case-insensitively and drops empty groups", () => {
    expect(filterGroupsByQuery(GROUPS, "INVENTORY").map((g) => g.categoryKey)).toEqual(["nautobot"]);
    expect(filterGroupsByQuery(GROUPS, "batfish-init")[0].items).toHaveLength(1);
    expect(filterGroupsByQuery(GROUPS, "nomatch")).toEqual([]);
  });
});
