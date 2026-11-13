"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import type { ReportRunResult } from "../types/ai-assistant";

interface ReportGenerateResponse {
  snapshot_id: number;
  name: string;
  status: string;
  sections_failed: number;
}

/**
 * The user's click on a proposed report. The report (sections, queries, layout) is in the signed
 * token, so the request cannot generate more than the card showed. Not retried: a retry would
 * make a second snapshot.
 */
export function useReportGenerateConfirmMutation() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async (token: string): Promise<ReportRunResult> => {
      const response = await apiCall<ReportGenerateResponse>(
        "ai/exec/report-generate",
        { method: "POST", body: JSON.stringify({ token }) },
      );
      return {
        snapshotId: response.snapshot_id,
        name: response.name,
        status: response.status,
        sectionsFailed: response.sections_failed,
      };
    },
  });
}
