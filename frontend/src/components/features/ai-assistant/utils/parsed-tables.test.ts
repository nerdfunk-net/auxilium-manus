import { describe, expect, it } from "vitest";

import {
  MAX_TABLE_ROWS,
  columnLabel,
  parseParsedTables,
  parsedTextWasCut,
} from "./parsed-tables";

const CDP = JSON.stringify([
  {
    command: "show cdp neighbors detail",
    error: null,
    parsed: [
      {
        neighbor_name: "sw2.example.com",
        mgmt_address: "192.0.2.2",
        platform: "cisco WS-C3850",
        neighbor_interface: "Gi0/24",
        local_interface: "Gi1/0/1",
        neighbor_description: "Cisco IOS Software",
        capabilities: "Switch IGMP",
        serial: "",
      },
      {
        neighbor_name: "r2",
        mgmt_address: "10.9.9.2",
        platform: "cisco ISR4331",
        neighbor_interface: "Gi0/0/1",
        local_interface: "Gi1/0/2",
        neighbor_description: "Cisco IOS XE",
        capabilities: "Router",
        serial: "",
      },
    ],
  },
]);

describe("parseParsedTables", () => {
  it("turns TextFSM rows into a table with the useful columns first", () => {
    const tables = parseParsedTables(CDP);

    expect(tables).toHaveLength(1);
    expect(tables[0].command).toBe("show cdp neighbors detail");
    expect(tables[0].columns.map((c) => c.label)).toEqual([
      "Local interface",
      "Neighbor",
      "Neighbor interface",
      "Management IP",
      "Platform",
      "Capabilities",
      "Neighbor description",
    ]);
    expect(tables[0].rows[0]).toEqual([
      "Gi1/0/1",
      "sw2.example.com",
      "Gi0/24",
      "192.0.2.2",
      "cisco WS-C3850",
      "Switch IGMP",
      "Cisco IOS Software",
    ]);
    expect(tables[0].totalRows).toBe(2);
  });

  it("drops columns that are empty in every row", () => {
    const [table] = parseParsedTables(CDP);

    expect(table.columns.map((c) => c.key)).not.toContain("serial");
  });

  it("writes lists and numbers as text and never throws on odd values", () => {
    const [table] = parseParsedTables(
      JSON.stringify([
        {
          command: "x",
          parsed: [
            { a: ["b", "c"], n: 5, flag: true, none: null, o: { k: 1 } },
          ],
        },
      ]),
    );

    expect(table.rows[0]).toEqual(["b, c", "5", "true", '{"k":1}']);
  });

  it("keeps one table per command and skips commands that did not parse", () => {
    const tables = parseParsedTables(
      JSON.stringify([
        { command: "a", parsed: [{ x: "1" }] },
        { command: "b", parsed: null, error: "No TextFSM template" },
        { command: "c", parsed: [{ y: "2" }] },
      ]),
    );

    expect(tables.map((t) => t.command)).toEqual(["a", "c"]);
  });

  it("skips Genie-style nested data and empty results", () => {
    expect(
      parseParsedTables(
        JSON.stringify([
          { command: "g", parsed: { version: { os: "ios" } } },
          { command: "e", parsed: [] },
        ]),
      ),
    ).toEqual([]);
  });

  it("returns nothing for text that is not the expected JSON", () => {
    expect(parseParsedTables("")).toEqual([]);
    expect(parseParsedTables("[{ cut off")).toEqual([]);
    expect(parseParsedTables('{"a": 1}')).toEqual([]);
    expect(parseParsedTables("[1, null, 'x']")).toEqual([]);
  });

  it("shows at most MAX_TABLE_ROWS rows and reports the total", () => {
    const rows = Array.from({ length: MAX_TABLE_ROWS + 5 }, (_, i) => ({
      n: String(i),
    }));

    const [table] = parseParsedTables(
      JSON.stringify([{ command: "big", parsed: rows }]),
    );

    expect(table.rows).toHaveLength(MAX_TABLE_ROWS);
    expect(table.totalRows).toBe(MAX_TABLE_ROWS + 5);
  });
});

describe("columnLabel", () => {
  it.each([
    ["neighbor_name", "Neighbor"],
    ["mgmt_address", "Management IP"],
    ["dead_time", "Dead time"],
    ["AS", "AS"],
    ["bgp_neigh", "Bgp neigh"],
    ["", ""],
  ])("%s -> %s", (key, label) => {
    expect(columnLabel(key)).toBe(label);
  });
});

describe("parsedTextWasCut", () => {
  it("recognises the notice the server appends when it cuts the parsed JSON", () => {
    const cut =
      '[{"command": "x", "parsed": [{"a": "1"},\n…[cut: showed 100000 of 250000 characters; the rest is in the handle]';

    expect(parsedTextWasCut(cut)).toBe(true);
    expect(parseParsedTables(cut)).toEqual([]);
  });

  it("is false for complete JSON and for nothing", () => {
    expect(parsedTextWasCut('[{"command": "x", "parsed": []}]')).toBe(false);
    expect(parsedTextWasCut("")).toBe(false);
  });
});
