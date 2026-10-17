import { describe, expect, it } from "vitest";

import { parseAuthUser } from "./auth-response-parser";

const VALID_PAYLOAD = {
  id: 1,
  username: "alice",
  is_active: true,
  roles: ["admin"],
  permissions: ["workflows:read"],
};

describe("parseAuthUser", () => {
  it("copies must_change_password through when true", () => {
    const result = parseAuthUser({ ...VALID_PAYLOAD, must_change_password: true });
    expect(result?.must_change_password).toBe(true);
  });

  it("copies must_change_password through when false", () => {
    const result = parseAuthUser({ ...VALID_PAYLOAD, must_change_password: false });
    expect(result?.must_change_password).toBe(false);
  });

  it("defaults must_change_password to false when absent (older backend)", () => {
    const result = parseAuthUser(VALID_PAYLOAD);
    expect(result?.must_change_password).toBe(false);
  });

  it("defaults must_change_password to false for a non-boolean value", () => {
    const result = parseAuthUser({ ...VALID_PAYLOAD, must_change_password: "true" });
    expect(result?.must_change_password).toBe(false);
  });

  it("still validates the required fields", () => {
    expect(parseAuthUser({ ...VALID_PAYLOAD, id: "not-a-number" })).toBeNull();
    expect(parseAuthUser({ ...VALID_PAYLOAD, roles: "admin" })).toBeNull();
  });

  it("rejects a non-object payload", () => {
    expect(parseAuthUser(null)).toBeNull();
    expect(parseAuthUser("a string")).toBeNull();
    expect(parseAuthUser(undefined)).toBeNull();
  });

  it("passes through the rest of the fields unchanged", () => {
    const result = parseAuthUser(VALID_PAYLOAD);
    expect(result).toEqual({ ...VALID_PAYLOAD, must_change_password: false });
  });
});
