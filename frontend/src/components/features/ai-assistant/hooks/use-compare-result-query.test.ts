import { describe, expect, it } from "vitest";

import { ApiError } from "@/hooks/use-api";

import {
  COMPARE_EXPIRED_MESSAGE,
  CompareExpiredError,
  isRetryableCompareError,
  shouldRetryCompare,
} from "./use-compare-result-query";

describe("compare result retry policy", () => {
  it("retries a transient failure once", () => {
    const failure = new Error("Network error");
    expect(shouldRetryCompare(0, failure)).toBe(true);
    expect(shouldRetryCompare(1, failure)).toBe(false);
    expect(shouldRetryCompare(0, new ApiError("Unavailable", 503))).toBe(true);
  });

  it("never retries an expiry or a refusal", () => {
    expect(shouldRetryCompare(0, new CompareExpiredError())).toBe(false);
    expect(shouldRetryCompare(0, new ApiError("Not found", 404))).toBe(false);
    expect(shouldRetryCompare(0, new ApiError("Forbidden", 403))).toBe(false);
  });

  it("offers a manual retry for the same errors it would retry", () => {
    expect(isRetryableCompareError(new Error("Network error"))).toBe(true);
    expect(isRetryableCompareError(new ApiError("Unavailable", 503))).toBe(true);
    expect(isRetryableCompareError(new CompareExpiredError())).toBe(false);
    expect(isRetryableCompareError(new ApiError("Forbidden", 403))).toBe(false);
  });

  it("words the expiry for the user", () => {
    expect(new CompareExpiredError().message).toBe(COMPARE_EXPIRED_MESSAGE);
  });
});
