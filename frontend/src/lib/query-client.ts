import { QueryClient } from "@tanstack/react-query";

const MAX_QUERY_RETRIES = 3;

/**
 * Retry transient failures only. A 4xx answer (permission denied, not found, invalid request)
 * will not change on retry, and retrying it keeps a loading state open for several seconds.
 * 408 (timeout) and 429 (rate limited) are transient and stay retryable.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status === "number" && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return false;
  }
  return failureCount < MAX_QUERY_RETRIES;
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        staleTime: 30 * 1000,
        refetchOnWindowFocus: true,
      },
    },
  });
}
