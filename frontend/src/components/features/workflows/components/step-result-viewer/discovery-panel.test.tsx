"use client";

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  DiscoveryPanel,
  extractDiscovery,
  isDiscoveryMetadataKey,
  reasonLabel,
} from "./discovery-panel";
import { metadataWithoutDebugPanels } from "./metadata-panel";
import type { DiscoveryPayload } from "./types";

afterEach(() => {
  cleanup();
});

const PAYLOAD: DiscoveryPayload = {
  visited: [
    { name: "core1", ip: "10.1.0.1", depth: 0, discovered_from: null, seed: true, cdp_status: "ok" },
    {
      name: "sw2.lab",
      ip: "10.1.0.2",
      depth: 1,
      discovered_from: "core1",
      seed: false,
      cdp_status: "not_enabled",
    },
  ],
  seen_not_visited: [
    {
      name: "far-sw",
      ip: "172.16.0.9",
      platform: "cisco WS-C3850",
      reason: "out_of_scope",
      seen_from: "core1",
      depth: 1,
    },
    { name: "ap-1", ip: null, platform: "", reason: "no_management_ip", seen_from: "sw2.lab", depth: 2 },
  ],
  edges: [
    { from: "core1", local_port: "Gi1/0/1", to: "sw2.lab", remote_port: "Gi1/0/48", to_ip: "10.1.0.2" },
  ],
  limits_hit: [],
  truncated: false,
};

describe("extractDiscovery", () => {
  it("finds the step record by its key suffix and shape", () => {
    const entries = extractDiscovery({ "disc-1.discovery": PAYLOAD, "other.log_attributes": {} });
    expect(entries).toHaveLength(1);
    expect(entries[0]?.nodeId).toBe("disc-1");
    expect(entries[0]?.payload.visited).toHaveLength(2);
  });

  it("ignores a .discovery key that is not a discovery record", () => {
    expect(extractDiscovery({ "x.discovery": "text" })).toEqual([]);
    expect(extractDiscovery({ "x.discovery": { visited: "no" } })).toEqual([]);
    expect(extractDiscovery({ "x.discovery": null })).toEqual([]);
  });

  it("tolerates missing optional lists", () => {
    const [entry] = extractDiscovery({ "n.discovery": { visited: [], seen_not_visited: [] } });
    expect(entry?.payload.edges).toEqual([]);
    expect(entry?.payload.limits_hit).toEqual([]);
    expect(entry?.payload.truncated).toBe(false);
  });
});

describe("metadata filtering", () => {
  it("removes the discovery record from the raw metadata list but keeps other keys", () => {
    expect(isDiscoveryMetadataKey("n.discovery", PAYLOAD)).toBe(true);
    expect(isDiscoveryMetadataKey("n.discovery", "text")).toBe(false);
    const rest = metadataWithoutDebugPanels({ "n.discovery": PAYLOAD, "n.total": 3 });
    expect(Object.keys(rest)).toEqual(["n.total"]);
  });
});

describe("reasonLabel", () => {
  it("explains every closed reason and falls back to the raw value", () => {
    expect(reasonLabel("out_of_scope")).toMatch(/outside the permitted/i);
    expect(reasonLabel("login_failed")).toMatch(/login/i);
    expect(reasonLabel("something_new")).toBe("something_new");
  });
});

describe("DiscoveryPanel", () => {
  it("renders nothing without entries", () => {
    const { container } = render(<DiscoveryPanel entries={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the counts, the visited devices and the devices that were not visited", () => {
    render(<DiscoveryPanel entries={[{ nodeId: "disc-1", payload: PAYLOAD }]} />);

    expect(screen.getByText(/2 visited/)).toBeTruthy();
    expect(screen.getByText(/2 seen, not visited/)).toBeTruthy();
    expect(screen.getByText(/1 link/)).toBeTruthy();

    const visited = screen.getByRole("table", { name: "Visited devices" });
    expect(within(visited).getAllByText("core1")).toHaveLength(2); // as device and as "found through"
    expect(within(visited).getByText("sw2.lab")).toBeTruthy();
    expect(within(visited).getByText("10.1.0.2")).toBeTruthy();
    expect(within(visited).getByText("seed")).toBeTruthy();
    expect(within(visited).getByText("not_enabled")).toBeTruthy();

    const seen = screen.getByRole("table", { name: "Seen, not visited" });
    expect(within(seen).getByText("far-sw")).toBeTruthy();
    expect(within(seen).getByText("172.16.0.9")).toBeTruthy();
    expect(within(seen).getByText(/outside the permitted/i)).toBeTruthy();
    expect(within(seen).getByText("no address")).toBeTruthy();
  });

  it("warns when a limit was hit or the lists were cut", () => {
    render(
      <DiscoveryPanel
        entries={[
          {
            nodeId: "n",
            payload: { ...PAYLOAD, limits_hit: ["max_devices", "max_depth"], truncated: true },
          },
        ]}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/max_devices/);
    expect(alert.textContent).toMatch(/max_depth/);
    expect(alert.textContent).toMatch(/cut|truncated/i);
  });

  it("shows no warning when nothing was cut", () => {
    render(<DiscoveryPanel entries={[{ nodeId: "n", payload: PAYLOAD }]} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists the links only after they are opened", () => {
    render(<DiscoveryPanel entries={[{ nodeId: "n", payload: PAYLOAD }]} />);
    expect(screen.queryByRole("table", { name: "Links" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /links/i }));
    const links = screen.getByRole("table", { name: "Links" });
    expect(within(links).getByText("Gi1/0/48")).toBeTruthy();
  });

  it("says so when a list is empty", () => {
    render(
      <DiscoveryPanel
        entries={[{ nodeId: "n", payload: { ...PAYLOAD, seen_not_visited: [], edges: [] } }]}
      />,
    );
    expect(screen.getByText(/every neighbour that was found was visited/i)).toBeTruthy();
  });
});
