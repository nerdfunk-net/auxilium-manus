"use client";

import { useQuery } from "@tanstack/react-query";

import type { DatasetInfo } from "@/components/features/reports/types/report-query";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

/** Datasets (with typed fields) of one report source. Types come from recent rows, so stay fresh. */
export function useReportCatalogQuery(sourceId: string) {
  const { apiCall } = useApi();
  return useQuery<DatasetInfo[]>({
    queryKey: queryKeys.reports.catalog(sourceId),
    queryFn: () =>
      apiCall<DatasetInfo[]>(`reports/sources/${encodeURIComponent(sourceId)}/catalog`, {
        method: "GET",
      }),
    enabled: sourceId !== "",
    staleTime: 30 * 1000,
  });
}
