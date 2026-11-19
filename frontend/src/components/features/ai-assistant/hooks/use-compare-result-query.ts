"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError, useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

import { parseCompareResponse, type CompareResultData } from "../utils/compare-result";
import { RESULT_HANDLE } from "../utils/config-download";

export const COMPARE_EXPIRED_MESSAGE =
  "This comparison is no longer available: results are kept for a few hours and are gone " +
  "after a reload. Ask the assistant to compare again.";

/** The lists are gone (an unknown or expired handle): asking again cannot help. */
export class CompareExpiredError extends Error {
  constructor() {
    super(COMPARE_EXPIRED_MESSAGE);
    this.name = "CompareExpiredError";
  }
}

/** A 4xx answer (expired, withdrawn access, bad request) will not change on its own. */
function isFinalError(error: unknown): boolean {
  return (
    error instanceof CompareExpiredError ||
    (error instanceof ApiError && error.status >= 400 && error.status < 500)
  );
}

/** Whether a failed read is worth another try (a dropped connection, a 5xx). */
export function isRetryableCompareError(error: unknown): boolean {
  return !isFinalError(error);
}

/** One automatic retry for a transient failure, none for a final answer. */
export function shouldRetryCompare(failureCount: number, error: unknown): boolean {
  return failureCount < 1 && isRetryableCompareError(error);
}

/**
 * The two lists of a file comparison, read from the server's short-lived result store as the
 * signed-in user (the model never sees them). A result is never refetched on its own; a
 * transient failure is retried once, a refusal (expired, or a permission withdrawn) is not.
 */
export function useCompareResultQuery(handle: string) {
  const { apiCall } = useApi();

  return useQuery<CompareResultData, Error>({
    queryKey: queryKeys.ai.compareResult(handle),
    enabled: RESULT_HANDLE.test(handle),
    retry: shouldRetryCompare,
    staleTime: Infinity,
    gcTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      try {
        const response = await apiCall<unknown>(`ai/results/${handle}/compare`, {
          method: "GET",
        });
        const data = parseCompareResponse(response);
        if (!data) {
          throw new Error("The comparison could not be read.");
        }
        return data;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          throw new CompareExpiredError();
        }
        throw error;
      }
    },
  });
}
