import { describe, expect, it } from "vitest";

import { formatRecipients, MAX_RECIPIENTS, parseRecipients } from "./recipients";

describe("parseRecipients", () => {
  it("splits on commas, semicolons, spaces and line breaks and removes duplicates", () => {
    const result = parseRecipients("a@example.org, b@example.org;c@example.org\nd@example.org  a@example.org");

    expect(result.addresses).toEqual([
      "a@example.org",
      "b@example.org",
      "c@example.org",
      "d@example.org",
    ]);
    expect(result.invalid).toEqual([]);
  });

  it("reports what is not an address", () => {
    const result = parseRecipients("ok@example.org, nope, @x.org, a@b");

    expect(result.addresses).toEqual(["ok@example.org", "a@b"]);
    expect(result.invalid).toEqual(["nope", "@x.org"]);
  });

  it("is empty for blank text", () => {
    expect(parseRecipients("  \n ")).toEqual({ addresses: [], invalid: [], tooMany: false });
  });

  it("flags too many recipients", () => {
    const text = Array.from({ length: MAX_RECIPIENTS + 1 }, (_, i) => `u${i}@example.org`).join(",");

    expect(parseRecipients(text).tooMany).toBe(true);
    expect(parseRecipients("a@example.org").tooMany).toBe(false);
  });
});

describe("formatRecipients", () => {
  it("joins one address per line", () => {
    expect(formatRecipients(["a@example.org", "b@example.org"])).toBe("a@example.org\nb@example.org");
  });
});
