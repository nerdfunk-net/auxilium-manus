import { describe, expect, it } from "vitest";

import { parseAndVerifyOidcState } from "./oidc-state";

describe("parseAndVerifyOidcState", () => {
  it("fails closed when stored state is missing", () => {
    expect(parseAndVerifyOidcState(null, "lab:abc")).toEqual({
      ok: false,
      error: "Missing state parameter — possible CSRF attempt",
    });
  });

  it("returns the provider id when stored and incoming state match", () => {
    expect(parseAndVerifyOidcState("lab:abc", "lab:abc")).toEqual({
      ok: true,
      providerId: "lab",
    });
  });

  it("rejects a mismatched incoming state", () => {
    expect(parseAndVerifyOidcState("lab:abc", "lab:evil")).toEqual({
      ok: false,
      error: "Invalid state parameter — possible CSRF attempt",
    });
  });

  it("rejects a case-mismatched state", () => {
    expect(parseAndVerifyOidcState("lab:abc", "LAB:abc")).toEqual({
      ok: false,
      error: "Invalid state parameter — possible CSRF attempt",
    });
  });

  it("rejects a matching value that is not provider:nonce form", () => {
    expect(parseAndVerifyOidcState("not-a-provider", "not-a-provider")).toEqual({
      ok: false,
      error: "Invalid state parameter",
    });
  });
});
