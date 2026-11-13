"use client";

import { useMutation } from "@tanstack/react-query";

import { buildApiErrorMessage } from "@/hooks/use-api";
import { useAuthStore } from "@/lib/auth-store";

/** What a snapshot can be downloaded as: the report text as PDF, the raw section data as CSV. */
export type SnapshotDownloadFormat = "pdf" | "csv";

function fileNameFrom(disposition: string | null, fallback: string): string {
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? fallback;
}

/**
 * Downloads a snapshot through the proxy (the browser saves the file). The CSV is one file for a
 * report with one section and a zip with one file per section otherwise; the server names it.
 */
export function useReportSnapshotDownload(format: SnapshotDownloadFormat) {
  return useMutation<void, Error, number>({
    mutationFn: async (snapshotId) => {
      const response = await fetch(
        `/api/proxy/reports/snapshots/${snapshotId}/${format}`,
        { credentials: "include" },
      );
      if (!response.ok) {
        throw new Error(
          await buildApiErrorMessage(response, () =>
            useAuthStore.getState().markPasswordChangeRequired(),
          ),
        );
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileNameFrom(
        response.headers.get("Content-Disposition"),
        `report-${snapshotId}.${format}`,
      );
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  });
}
