import { describe, expect, it } from "vitest";

import {
  ACCOUNT_PASSWORD_MIN_LENGTH,
  insecurePasswordReason,
  isRemoteLoginSecret,
} from "./insecure-password";

describe("isRemoteLoginSecret", () => {
  it("covers SSH logins and Basic Auth only", () => {
    expect(isRemoteLoginSecret("ssh")).toBe(true);
    expect(isRemoteLoginSecret("generic")).toBe(true);
    expect(isRemoteLoginSecret("token")).toBe(false);
    expect(isRemoteLoginSecret("shared_secret")).toBe(false);
    expect(isRemoteLoginSecret("ssh_key")).toBe(false);
  });
});

describe("insecurePasswordReason", () => {
  it("flags a password under the account minimum", () => {
    const reason = insecurePasswordReason("x".repeat(ACCOUNT_PASSWORD_MIN_LENGTH - 1), "admin");
    expect(reason).toContain(String(ACCOUNT_PASSWORD_MIN_LENGTH));
  });

  it("accepts a password that meets the account rules", () => {
    expect(insecurePasswordReason("correct-horse-battery", "admin")).toBeNull();
  });

  it("flags a password that matches the username", () => {
    const password = "administrator";
    expect(password.length).toBeGreaterThanOrEqual(ACCOUNT_PASSWORD_MIN_LENGTH);
    expect(insecurePasswordReason(password, "Administrator")).toContain("username");
  });

  it("treats an empty password as unset", () => {
    expect(insecurePasswordReason("", "admin")).toBeNull();
  });
});
