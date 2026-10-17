"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  ReportDefinition,
  ReportDefinitionSummary,
} from "@/components/features/reports/types/report-definition";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useReportDefinitionsQuery() {
  const { apiCall } = useApi();
  return useQuery<ReportDefinitionSummary[]>({
    queryKey: queryKeys.reports.definitions(),
    queryFn: () =>
      apiCall<ReportDefinitionSummary[]>("reports/definitions", { method: "GET" }),
    staleTime: 30 * 1000,
  });
}

/** One full definition (with its sections); disabled until an id is given. */
export function useReportDefinitionQuery(id: number | null) {
  const { apiCall } = useApi();
  return useQuery<ReportDefinition>({
    queryKey: queryKeys.reports.definition(id ?? 0),
    queryFn: () =>
      apiCall<ReportDefinition>(`reports/definitions/${id}`, { method: "GET" }),
    enabled: id !== null,
    staleTime: 0,
  });
}
