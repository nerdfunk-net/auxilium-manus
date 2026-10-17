import { describe, expect, it } from "vitest";

import { ApiError } from "@/hooks/use-api";

import { dependantsFromError, describeDependantKind } from "./credential-dependants";

const dependants = [{ kind: "git_repository", id: 3, name: "configs" }];

describe("dependantsFromError", () => {
  it("returns the list from a credential_in_use conflict", () => {
    const error = new ApiError("in use", 409, { code: "credential_in_use", dependants });
    expect(dependantsFromError(error)).toEqual(dependants);
  });

  it("returns null for any other error", () => {
    expect(dependantsFromError(new ApiError("x", 409, { code: "other" }))).toBeNull();
    expect(dependantsFromError(new ApiError("x", 500, null))).toBeNull();
    expect(dependantsFromError(new Error("x"))).toBeNull();
    expect(dependantsFromError(null)).toBeNull();
  });

  it("drops malformed entries instead of rendering them", () => {
    const error = new ApiError("in use", 409, {
      code: "credential_in_use",
      dependants: [...dependants, { kind: 1 }, "x", null],
    });
    expect(dependantsFromError(error)).toEqual(dependants);
  });
});

describe("describeDependantKind", () => {
  it("labels the known kinds and falls back to the raw kind", () => {
    expect(describeDependantKind("git_repository")).toBe("Git repository");
    expect(describeDependantKind("workflow")).toBe("Workflow");
    expect(describeDependantKind("mystery")).toBe("mystery");
  });
});
