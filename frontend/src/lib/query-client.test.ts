import { describe, expect, it } from "vitest";

import { createQueryClient, shouldRetryQuery } from "./query-client";

const failure = (status?: number) => Object.assign(new Error("x"), status === undefined ? {} : { status });

describe("shouldRetryQuery", () => {
  it.each([400, 401, 403, 404, 409, 422])("does not retry a %i answer", (status) => {
    expect(shouldRetryQuery(0, failure(status))).toBe(false);
  });

  it.each([408, 429])("retries the transient %i", (status) => {
    expect(shouldRetryQuery(0, failure(status))).toBe(true);
  });

  it.each([500, 502, 503])("retries a %i server error", (status) => {
    expect(shouldRetryQuery(0, failure(status))).toBe(true);
  });

  it("retries an error without a status (network failure) up to three times", () => {
    expect(shouldRetryQuery(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetryQuery(2, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetryQuery(3, new TypeError("Failed to fetch"))).toBe(false);
  });

  it("stops retrying a server error after three attempts", () => {
    expect(shouldRetryQuery(3, failure(500))).toBe(false);
  });

  it("tolerates a null or non-object error", () => {
    expect(shouldRetryQuery(0, null)).toBe(true);
    expect(shouldRetryQuery(0, "boom")).toBe(true);
  });
});

describe("createQueryClient", () => {
  it("uses the retry policy for queries", () => {
    const options = createQueryClient().getDefaultOptions().queries;
    expect(options?.retry).toBe(shouldRetryQuery);
    expect(options?.refetchOnWindowFocus).toBe(true);
  });
});
