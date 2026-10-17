"use client";

import { useQuery } from "@tanstack/react-query";

import type {
  ReportSnapshot,
  ReportSnapshotSummary,
} from "@/components/features/reports/types/report-definition";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export function useReportSnapshotsQuery(definitionId?: number) {
  const { apiCall } = useApi();
  const suffix = definitionId === undefined ? "" : `?definition_id=${definitionId}`;
  return useQuery<ReportSnapshotSummary[]>({
    queryKey: queryKeys.reports.snapshotList(definitionId),
    queryFn: () =>
      apiCall<ReportSnapshotSummary[]>(`reports/snapshots${suffix}`, { method: "GET" }),
    staleTime: 30 * 1000,
  });
}

/** One snapshot with its content. A snapshot never changes, so it is cached for a while. */
export function useReportSnapshotQuery(id: number | null) {
  const { apiCall } = useApi();
  return useQuery<ReportSnapshot>({
    queryKey: queryKeys.reports.snapshot(id ?? 0),
    queryFn: () => apiCall<ReportSnapshot>(`reports/snapshots/${id}`, { method: "GET" }),
    enabled: id !== null,
    staleTime: 5 * 60 * 1000,
  });
}
