import { describe, expect, it } from "vitest";

import {
  activeFilters,
  FILTER_KIND_BY_KEY,
  FILTER_KINDS,
  filtersFromConfig,
  presentKinds,
  toggleOption,
} from "./filter-kinds";

describe("FILTER_KINDS", () => {
  it("mirrors the filter keys of services/aci/device_filters.py", () => {
    expect(FILTER_KINDS.map((kind) => kind.key).sort()).toEqual(
      [
        "cidr",
        "fabric_states",
        "models",
        "names",
        "node_ids",
        "pod_ids",
        "roles",
        "serials",
        "versions",
      ].sort(),
    );
  });

  it("only offers the two roles the backend accepts (never the APIC controller)", () => {
    expect(FILTER_KIND_BY_KEY.roles.options).toEqual(["leaf", "spine"]);
  });

  it("describes the ACI wildcards, not Catalyst's .* dialect", () => {
    const hints = FILTER_KINDS.map((kind) => `${kind.hint} ${kind.placeholder}`).join(" ");
    expect(hints).not.toContain(".*");
    expect(FILTER_KIND_BY_KEY.names.hint).toContain("*");
  });

  it("holds one string for cidr and a list for every other kind", () => {
    expect(FILTER_KINDS.filter((kind) => kind.single).map((kind) => kind.key)).toEqual(["cidr"]);
  });
});

describe("filtersFromConfig", () => {
  it("returns nothing for a missing or malformed filters value", () => {
    for (const config of [{}, { filters: null }, { filters: [] }, { filters: "names" }]) {
      expect(filtersFromConfig(config)).toEqual({});
    }
  });

  it("drops unknown keys (for example a Catalyst key pasted in)", () => {
    expect(filtersFromConfig({ filters: { hostnames: ["a"], names: ["leaf-*"] } })).toEqual({
      names: ["leaf-*"],
    });
  });

  it("repairs values of the wrong shape instead of passing them on", () => {
    expect(
      filtersFromConfig({ filters: { names: "leaf-1", cidr: 5, models: ["a", 3, "b"] } }),
    ).toEqual({ names: [], cidr: "", models: ["a", "b"] });
  });

  it("keeps numeric ids a config stored as numbers, shown as the text the textarea edits", () => {
    // The backend (and registry.yaml's example) accept [1] as well as ["1"]; neither may be lost.
    expect(filtersFromConfig({ filters: { node_ids: [101, "102"], pod_ids: [1, 2] } })).toEqual({
      node_ids: ["101", "102"],
      pod_ids: ["1", "2"],
    });
  });

  it("drops what is not a whole number from an id list, but keeps text for the backend to name", () => {
    expect(
      filtersFromConfig({
        filters: { node_ids: [101, 1.5, Number.NaN, Infinity, true, null, "abc"] },
      }),
    ).toEqual({ node_ids: ["101", "abc"] });
  });

  it("still drops numbers from the text filters", () => {
    expect(filtersFromConfig({ filters: { names: ["leaf", 7], serials: [1] } })).toEqual({
      names: ["leaf"],
      serials: [],
    });
  });

  it("round-trips: numbers in the config reach the preview request as numbers", () => {
    const filters = filtersFromConfig({ filters: { node_ids: [101, 102], pod_ids: [1] } });
    expect(activeFilters(filters)).toEqual({ node_ids: [101, 102], pod_ids: [1] });
  });
});

describe("activeFilters", () => {
  it("trims values and drops blank lines and empty kinds", () => {
    expect(
      activeFilters({ names: [" leaf-* ", "", "  "], models: [], cidr: "  ", serials: ["X"] }),
    ).toEqual({ names: ["leaf-*"], serials: ["X"] });
  });

  it("sends digit-only pod and node ids as numbers", () => {
    expect(activeFilters({ node_ids: ["101", " 102 ", ""], pod_ids: ["1"] })).toEqual({
      node_ids: [101, 102],
      pod_ids: [1],
    });
  });

  it("leaves a non-numeric id as text so the backend can name the problem", () => {
    expect(activeFilters({ node_ids: ["101", "abc", "-5"] })).toEqual({
      node_ids: [101, "abc", "-5"],
    });
  });

  it("does not turn digit-only text filters into numbers", () => {
    expect(activeFilters({ serials: ["123"], versions: ["16"] })).toEqual({
      serials: ["123"],
      versions: ["16"],
    });
  });

  it("keeps a trimmed cidr and roles as they are", () => {
    expect(activeFilters({ cidr: " 10.1.1.0/24 ", roles: ["leaf"] })).toEqual({
      cidr: "10.1.1.0/24",
      roles: ["leaf"],
    });
  });

  it("is empty when nothing is set, which is what the allow_all guard checks", () => {
    expect(activeFilters({})).toEqual({});
    expect(activeFilters({ roles: [], names: [""] })).toEqual({});
  });
});

describe("presentKinds", () => {
  it("lists the configured kinds in the canonical display order", () => {
    expect(presentKinds({ cidr: "", names: [], roles: [] }).map((kind) => kind.key)).toEqual([
      "names",
      "roles",
      "cidr",
    ]);
  });

  it("is empty for no filters", () => {
    expect(presentKinds({})).toEqual([]);
  });
});

describe("the role filter hint", () => {
  it("does not claim that an unticked role row selects both roles on its own", () => {
    const hint = FILTER_KIND_BY_KEY.roles.hint;
    expect(hint).toMatch(/not a filter/i);
    expect(hint).toMatch(/another filter or allow_all/);
    expect(hint).not.toMatch(/leave both unticked to take/i);
  });
});

describe("toggleOption", () => {
  const order = ["leaf", "spine"] as const;

  it("adds an option and keeps the canonical order", () => {
    expect(toggleOption(["spine"], "leaf", order)).toEqual(["leaf", "spine"]);
  });

  it("removes an option that is already selected", () => {
    expect(toggleOption(["leaf", "spine"], "leaf", order)).toEqual(["spine"]);
  });

  it("does not mutate its input", () => {
    const input = ["leaf"];
    toggleOption(input, "spine", order);
    expect(input).toEqual(["leaf"]);
  });

  it("keeps values outside the known options so an edited config is not silently changed", () => {
    expect(toggleOption(["controller"], "leaf", order)).toEqual(["leaf", "controller"]);
  });
});
