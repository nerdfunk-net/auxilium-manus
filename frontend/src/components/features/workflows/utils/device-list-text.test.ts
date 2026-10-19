import { describe, expect, it } from "vitest";

import {
  DEFAULT_NETWORK_DRIVER,
  driverForSuggestion,
  parseDeviceLine,
  parseDeviceListText,
  serializeDeviceRows,
} from "./device-list-text";

describe("parseDeviceListText", () => {
  it("reads name,ip,driver lines", () => {
    expect(parseDeviceListText("r1,10.0.0.1,junos")).toEqual([
      { name: "r1", ip: "10.0.0.1", driver: "junos" },
    ]);
  });

  it("keeps an empty IP between name and driver", () => {
    expect(parseDeviceListText("r1,,cisco_nxos")).toEqual([
      { name: "r1", ip: "", driver: "cisco_nxos" },
    ]);
  });

  it("fills the default driver for legacy one- and two-field lines", () => {
    expect(parseDeviceListText("r1\n10.0.0.5\nr2,10.0.0.6", "cisco_xe")).toEqual([
      { name: "r1", ip: "", driver: "cisco_xe" },
      { name: "", ip: "10.0.0.5", driver: "cisco_xe" },
      { name: "r2", ip: "10.0.0.6", driver: "cisco_xe" },
    ]);
  });

  it("defaults to cisco_ios and ignores blank lines", () => {
    expect(DEFAULT_NETWORK_DRIVER).toBe("cisco_ios");
    expect(parseDeviceListText("\n r1 \n\n")).toEqual([
      { name: "r1", ip: "", driver: "cisco_ios" },
    ]);
  });
});

describe("serializeDeviceRows", () => {
  it("writes the driver when set and drops empty rows", () => {
    expect(
      serializeDeviceRows([
        { name: "r1", ip: "10.0.0.1", driver: "junos" },
        { name: "", ip: "", driver: "cisco_ios" },
        { name: "r2", ip: "", driver: "" },
        { name: "", ip: "10.0.0.3", driver: "" },
      ]),
    ).toBe("r1,10.0.0.1,junos\nr2\n10.0.0.3");
  });

  it("keeps the empty IP slot when only a name and a driver are set", () => {
    expect(serializeDeviceRows([{ name: "r1", ip: "", driver: "junos" }])).toBe("r1,,junos");
  });

  it("round-trips", () => {
    const text = "r1,10.0.0.1,junos\nr2,,cisco_nxos";
    expect(serializeDeviceRows(parseDeviceListText(text))).toBe(text);
  });
});

describe("driverForSuggestion", () => {
  it("uses the inventory device's driver when it has one", () => {
    expect(driverForSuggestion({ network_driver: " juniper_junos " }, "cisco_ios")).toBe(
      "juniper_junos",
    );
  });

  it("falls back to the step default when the device has none", () => {
    expect(driverForSuggestion({ network_driver: null }, "cisco_nxos")).toBe("cisco_nxos");
    expect(driverForSuggestion({ network_driver: "  " }, "cisco_nxos")).toBe("cisco_nxos");
    expect(driverForSuggestion({}, "cisco_nxos")).toBe("cisco_nxos");
  });
});

describe("backend parity", () => {
  it("rejects lines with more than three fields instead of dropping the extras", () => {
    expect(parseDeviceLine("r1,10.0.0.1,junos,extra")).toBeNull();
    expect(parseDeviceListText("r1,10.0.0.1,junos,extra\nr2")).toEqual([
      { name: "r2", ip: "", driver: "cisco_ios" },
    ]);
  });

  it("treats a token as an IP only when the backend does", () => {
    expect(parseDeviceListText("dead:beef")).toEqual([
      { name: "dead:beef", ip: "", driver: "cisco_ios" },
    ]);
    expect(parseDeviceListText("2001:db8::1")[0]).toMatchObject({ name: "", ip: "2001:db8::1" });
  });

  it("never serializes a comma or line break inside a field", () => {
    const text = serializeDeviceRows([{ name: "edge,10.1.1.1", ip: "", driver: "cisco_ios" }]);
    expect(text.split("\n")).toHaveLength(1);
    expect(text.split(",")).toHaveLength(3);
    expect(parseDeviceListText(text)).toEqual([
      { name: "edge10.1.1.1", ip: "", driver: "cisco_ios" },
    ]);
  });
});
