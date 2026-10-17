"use client";

import { useMutation } from "@tanstack/react-query";

import type {
  QueryResult,
  ReportQuerySpec,
} from "@/components/features/reports/types/report-query";
import { useApi } from "@/hooks/use-api";

/** Runs a report query. A read, but sent on demand, so it is a mutation; the error is shown inline. */
export function useReportQueryMutation() {
  const { apiCall } = useApi();
  return useMutation<QueryResult, Error, ReportQuerySpec>({
    mutationFn: (query) =>
      apiCall<QueryResult>(`reports/sources/${encodeURIComponent(query.source)}/query`, {
        method: "POST",
        body: JSON.stringify(query),
      }),
  });
}
