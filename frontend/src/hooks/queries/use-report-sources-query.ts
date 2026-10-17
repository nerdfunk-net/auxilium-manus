"use client";

import { useQuery } from "@tanstack/react-query";

import type { ReportSource } from "@/components/features/reports/types/report-query";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useReportSourcesQuery() {
  const { apiCall } = useApi();
  return useQuery<ReportSource[]>({
    queryKey: queryKeys.reports.sources(),
    queryFn: () => apiCall<ReportSource[]>("reports/sources", { method: "GET" }),
    staleTime: 5 * 60 * 1000,
  });
}
