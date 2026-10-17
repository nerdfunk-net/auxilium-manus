import { describe, expect, it } from "vitest";

import {
  addRoute,
  buildRouteOnAttributeConfig,
  deriveRouteOutcomes,
  editableRoutes,
  removeRoute,
  routeOutcomeProblem,
  sameValues,
  setRouteOutcome,
  setRouteValues,
  isReservedRouteName,
  parseRouteOnAttributeConfig,
  splitRouteValues,
} from "./route-config";

describe("route-on-attribute outcomes", () => {
  it("appends the failure handle", () => {
    const outcomes = deriveRouteOutcomes({
      attribute_path: "network_driver",
      routes: [{ outcome: "ios", values: ["cisco_ios"] }],
      default_outcome: "unmatched",
    });
    expect(outcomes.map((o) => o.name)).toEqual(["ios", "unmatched", "failure"]);
  });

  it("rejects reserved route names", () => {
    expect(isReservedRouteName("success")).toBe(true);
    expect(isReservedRouteName(" failure ")).toBe(true);
    expect(isReservedRouteName("ios")).toBe(false);
  });
});

describe("splitRouteValues", () => {
  it("splits a plain comma list", () => {
    expect(splitRouteValues("cisco_ios, ios")).toEqual(["cisco_ios", "ios"]);
  });

  it("keeps commas inside an expression", () => {
    expect(splitRouteValues("{x:in('a','b')}, plain, {:gt(1)}")).toEqual([
      "{x:in('a','b')}",
      "plain",
      "{:gt(1)}",
    ]);
  });

  it("does not treat an apostrophe in a plain value as a quote", () => {
    expect(splitRouteValues("it's, ok")).toEqual(["it's", "ok"]);
  });

  it("keeps a half-typed expression together", () => {
    expect(splitRouteValues("{x:in('a',")).toEqual(["{x:in('a',"]);
  });

  it("does not end a quoted part at an escaped quote", () => {
    expect(splitRouteValues("{x:in('a\\',b','c')}, plain")).toEqual([
      "{x:in('a\\',b','c')}",
      "plain",
    ]);
  });

  it("drops blank entries", () => {
    expect(splitRouteValues(" , a ,, ")).toEqual(["a"]);
  });
});

describe("parseRouteOnAttributeConfig", () => {
  it("splits a string values field expression-aware", () => {
    const parsed = parseRouteOnAttributeConfig({
      routes: [{ outcome: "hit", values: "x, {:in('a','b')}" }],
    });
    expect(parsed.routes[0].values).toEqual(["x", "{:in('a','b')}"]);
  });
});

describe("route table editing", () => {
  const routes = [
    { outcome: "ios", values: ["cisco_ios"] },
    { outcome: "nxos", values: ["cisco_nxos"] },
  ];

  it("keeps a row whose outcome was cleared", () => {
    const cleared = setRouteOutcome(routes, 0, "");
    expect(editableRoutes({ routes: cleared })).toHaveLength(2);
    expect(editableRoutes({ routes: cleared })[0].outcome).toBe("");
  });

  it("falls back to the defaults when no routes are stored", () => {
    expect(editableRoutes({}).map((r) => r.outcome)).toEqual(["ios", "nxos"]);
  });

  it("edits without mutating the input", () => {
    const next = setRouteValues(routes, 1, ["a", "b"]);
    expect(next[1].values).toEqual(["a", "b"]);
    expect(routes[1].values).toEqual(["cisco_nxos"]);
  });

  it("adds a route with a free default name", () => {
    const next = addRoute([...routes, { outcome: "route-3", values: [] }]);
    expect(next.map((r) => r.outcome)).toEqual(["ios", "nxos", "route-3", "route-4"]);
  });

  it("never removes the last route", () => {
    expect(removeRoute(routes, 0).map((r) => r.outcome)).toEqual(["nxos"]);
    const single = [routes[0]];
    expect(removeRoute(single, 0)).toBe(single);
  });

  it("reports empty, reserved and duplicate outcome names", () => {
    const bad = [
      { outcome: "", values: [] },
      { outcome: "failure", values: [] },
      { outcome: "a", values: [] },
      { outcome: "a", values: [] },
      { outcome: "ok", values: [] },
    ];
    expect(routeOutcomeProblem(bad, 0)).toMatch(/needs a name/);
    expect(routeOutcomeProblem(bad, 1)).toMatch(/reserved/);
    expect(routeOutcomeProblem(bad, 2)).toMatch(/twice/);
    expect(routeOutcomeProblem(bad, 4)).toBeNull();
  });

  it("compares value lists by content", () => {
    expect(sameValues(["a", "b"], ["a", "b"])).toBe(true);
    expect(sameValues(["a"], ["a", "b"])).toBe(false);
  });
});

describe("buildRouteOnAttributeConfig", () => {
  const withBlank = {
    attribute_path: "device.name",
    routes: [
      { outcome: "", values: ["{custom.value:gt(10)}"] },
      { outcome: "nxos", values: ["cisco_nxos"] },
    ],
  };

  it("keeps a blank-named route when another field is edited", () => {
    const next = buildRouteOnAttributeConfig(withBlank, { case_sensitive: true });
    expect(next.routes).toEqual(withBlank.routes);
    expect(next.case_sensitive).toBe(true);
  });

  it("keeps the expressions typed on blank rows when every route is blank", () => {
    const allBlank = { routes: [{ outcome: " ", values: ["{:exists()}"] }] };
    const next = buildRouteOnAttributeConfig(allBlank, { default_outcome: "other" });
    expect(next.routes).toEqual([{ outcome: " ", values: ["{:exists()}"] }]);
  });

  it("lets an explicit routes patch win", () => {
    const patched = [{ outcome: "a", values: [] }];
    expect(buildRouteOnAttributeConfig(withBlank, { routes: patched }).routes).toBe(patched);
  });

  it("falls back to the defaults for an empty routes array", () => {
    expect(editableRoutes({ routes: [] }).map((r) => r.outcome)).toEqual(["ios", "nxos"]);
  });
});
