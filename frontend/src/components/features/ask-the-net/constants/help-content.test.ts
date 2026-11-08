import { describe, expect, it } from "vitest";

import { HELP_SECTIONS } from "./help-content";

const tools = HELP_SECTIONS.flatMap((section) =>
  section.tools.map((tool) => ({ section: section.id, ...tool })),
);
const byName = (needle: string) =>
  tools.find((tool) => tool.name.includes(needle));

describe("Ask the Net help: finding an interface by MAC address", () => {
  it("lists list_interfaces_by_mac in the Nautobot section with questions that use it", () => {
    const tool = byName("list_interfaces_by_mac");

    expect(tool?.section).toBe("nautobot");
    expect(tool?.questions.join(" ")).toMatch(/MAC address/);
    expect(tool?.questions.some((q) => q.includes("AA:BB:CC:00:01:00"))).toBe(
      true,
    );
  });

  it("says the MAC is the documented one, not the switch's learned table, and who can use it", () => {
    const description = byName("list_interfaces_by_mac")?.description ?? "";

    expect(description).toMatch(/documented/i);
    expect(description).toMatch(/MAC address table/);
    expect(description).toMatch(/addresses/i);
  });

  it("mentions the MAC on the device and interface tools", () => {
    expect(byName("list_interfaces")?.description).toMatch(/MAC address/);
    expect(byName("list_devices")?.description).toMatch(/MAC address/);
  });

  it("points to the live device command for the learned MAC address table", () => {
    const live = byName("propose_device_command");

    expect(live?.section).toBe("device-commands");
    expect(
      live?.questions.some((q) =>
        /MAC address table|mac address-table/i.test(q),
      ),
    ).toBe(true);
  });

  it("keeps every tool entry complete", () => {
    for (const tool of tools) {
      expect(tool.name.length, tool.name).toBeGreaterThan(0);
      expect(tool.description.length, tool.name).toBeGreaterThan(10);
      expect(tool.questions.length, tool.name).toBeGreaterThan(0);
    }
  });
});

describe("Ask the Net help: feature learn", () => {
  const learn = HELP_SECTIONS.find((section) => section.id === "learn");

  it("lists the OSPF and BGP learn tools with questions that use them", () => {
    const names = learn?.tools.map((tool) => tool.name) ?? [];

    expect(names).toEqual([
      "propose_feature_learn",
      "get_bgp_learn_result",
      "propose_bgp_neighbor_detail",
      "compare_bgp_learns",
    ]);
    const questions =
      byName("propose_feature_learn")?.questions.join(" ") ?? "";
    expect(questions).toMatch(/OSPF/);
    expect(questions).toMatch(/BGP/);
  });

  it("tells the user to run the BGP learn twice and compare the runs later", () => {
    expect(learn?.summary).toMatch(/twice/);
    expect(learn?.summary).toMatch(/compare the two runs/i);
    expect(learn?.summary).toMatch(/few hours/);
    expect(byName("compare_bgp_learns")?.description).toMatch(/run it twice/i);
  });

  it("says what it needs and which platforms it supports", () => {
    expect(learn?.requirement).toMatch(/Genie/);
    expect(learn?.requirement).toMatch(/IOS-XE/);
  });
});
