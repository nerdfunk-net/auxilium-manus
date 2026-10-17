import { describe, expect, it } from "vitest";

import {
  boolField,
  joinedStringList,
  numberField,
  numberInputField,
  stringField,
} from "./config-field-helpers";

describe("config-field-helpers", () => {
  it("stringField returns strings, otherwise the fallback", () => {
    expect(stringField({ a: "x" }, "a")).toBe("x");
    expect(stringField({ a: 1 }, "a")).toBe("");
    expect(stringField({}, "a", "dflt")).toBe("dflt");
  });

  it("numberField returns numbers, otherwise the fallback", () => {
    expect(numberField({ a: 3 }, "a", 9)).toBe(3);
    expect(numberField({ a: "3" }, "a", 9)).toBe(9);
  });

  it("boolField returns booleans, otherwise the fallback", () => {
    expect(boolField({ a: true }, "a")).toBe(true);
    expect(boolField({ a: "true" }, "a")).toBe(false);
    expect(boolField({}, "a", true)).toBe(true);
  });

  it("numberInputField stringifies numbers and passes strings through", () => {
    expect(numberInputField({ a: 5 }, "a")).toBe("5");
    expect(numberInputField({ a: "7x" }, "a")).toBe("7x");
    expect(numberInputField({}, "a")).toBe("");
  });

  it("joinedStringList joins only string items", () => {
    expect(joinedStringList({ a: ["SSH", 1, "HTTPS"] }, "a")).toBe("SSH, HTTPS");
    expect(joinedStringList({ a: "SSH" }, "a")).toBe("");
  });
});
