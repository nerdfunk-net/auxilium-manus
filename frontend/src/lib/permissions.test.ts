import { describe, expect, it } from "vitest";

import type { AuthUser } from "@/lib/auth";

import { hasPermission, hasRole } from "./permissions";

const USER: AuthUser = {
  id: 1,
  username: "u",
  is_active: true,
  must_change_password: false,
  roles: ["viewer"],
  permissions: ["workflows:read", "workflows:execute"],
};

describe("hasPermission", () => {
  it("matches the exact resource:action pair", () => {
    expect(hasPermission(USER, "workflows", "read")).toBe(true);
    expect(hasPermission(USER, "workflows", "write")).toBe(false);
  });

  it("does not match by prefix or by resource alone", () => {
    expect(hasPermission(USER, "workflows", "")).toBe(false);
    expect(hasPermission(USER, "workflow", "read")).toBe(false);
    expect(hasPermission(USER, "workflows:read", "")).toBe(false);
  });

  it("denies everything without a user", () => {
    expect(hasPermission(null, "workflows", "read")).toBe(false);
    expect(hasRole(null, "admin")).toBe(false);
  });
});

describe("hasRole", () => {
  it("checks role membership", () => {
    expect(hasRole(USER, "viewer")).toBe(true);
    expect(hasRole(USER, "admin")).toBe(false);
  });
});
