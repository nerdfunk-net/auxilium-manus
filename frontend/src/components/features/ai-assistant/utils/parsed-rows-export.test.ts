import { describe, expect, it } from "vitest";

import {
  parsedRowsFileName,
  rowsToCsv,
  rowsToJson,
} from "./parsed-rows-export";

describe("rowsToJson", () => {
  it("is indented JSON of the rows", () => {
    expect(rowsToJson([{ a: 1 }])).toBe('[\n  {\n    "a": 1\n  }\n]');
  });
});

describe("rowsToCsv", () => {
  it("uses the union of the columns, _command first, and CRLF line ends", () => {
    const csv = rowsToCsv([
      { hostname: "r1", _command: "show version" },
      { _command: "show version", uptime: "1 day" },
    ]);

    expect(csv).toBe(
      "_command,hostname,uptime\r\nshow version,r1,\r\nshow version,,1 day",
    );
  });

  it("quotes commas, quotes and newlines", () => {
    const csv = rowsToCsv([{ a: 'x,"y"', b: "l1\nl2" }]);

    expect(csv).toBe('a,b\r\n"x,""y""","l1\nl2"');
  });

  it("writes nested values as JSON and null as empty", () => {
    const csv = rowsToCsv([{ a: ["x", "y"], b: null, c: { k: 1 }, d: 5 }]);

    expect(csv).toBe('a,b,c,d\r\n"[""x"",""y""]",,"{""k"":1}",5');
  });

  it("defuses cells a spreadsheet would run as a formula", () => {
    const csv = rowsToCsv([
      { a: "=HYPERLINK(1)", b: "+cmd|x", c: "@x", d: "-5", e: "ok" },
    ]);

    expect(csv).toBe("a,b,c,d,e\r\n'=HYPERLINK(1),'+cmd|x,'@x,-5,ok");
  });

  it("leaves numbers that merely start with a sign alone", () => {
    expect(rowsToCsv([{ a: "-5", b: "+1.5" }])).toBe("a,b\r\n-5,+1.5");
  });

  it("is just the empty string for no rows", () => {
    expect(rowsToCsv([])).toBe("");
  });
});

describe("parsedRowsFileName", () => {
  it("is a safe slug of the device with the extension", () => {
    expect(parsedRowsFileName("LAB.local.zz", "csv")).toBe(
      "lab-local-zz-parsed.csv",
    );
    expect(parsedRowsFileName("../../x y", "json")).toBe("x-y-parsed.json");
    expect(parsedRowsFileName("", "json")).toBe("device-parsed.json");
  });
});
