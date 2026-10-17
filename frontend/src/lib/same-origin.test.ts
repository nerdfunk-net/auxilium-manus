import { describe, expect, it } from "vitest";

import { isSameOriginRequest } from "./same-origin";

function post(headers: Record<string, string>) {
  return new Request("http://app.example/api/x", { method: "POST", headers });
}

describe("isSameOriginRequest", () => {
  it("rejects a cross-site fetch", () => {
    expect(isSameOriginRequest(post({ "sec-fetch-site": "cross-site" }))).toBe(false);
  });
  it("rejects a foreign Origin when Sec-Fetch-Site is absent", () => {
    expect(
      isSameOriginRequest(post({ origin: "https://evil.example", host: "app.example" })),
    ).toBe(false);
  });
  it("accepts same-origin requests", () => {
    expect(isSameOriginRequest(post({ "sec-fetch-site": "same-origin" }))).toBe(true);
    expect(isSameOriginRequest(post({ origin: "http://app.example", host: "app.example" }))).toBe(
      true,
    );
  });
  it("accepts non-browser clients and safe methods", () => {
    expect(isSameOriginRequest(post({}))).toBe(true);
    expect(
      isSameOriginRequest(
        new Request("http://app.example/x", { headers: { "sec-fetch-site": "cross-site" } }),
      ),
    ).toBe(true);
  });
});
