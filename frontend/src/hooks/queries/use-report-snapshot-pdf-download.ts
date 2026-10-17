"use client";

import { useMutation } from "@tanstack/react-query";

import { buildApiErrorMessage } from "@/hooks/use-api";
import { useAuthStore } from "@/lib/auth-store";

function fileNameFrom(disposition: string | null, fallback: string): string {
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? fallback;
}

/** Downloads a snapshot as PDF through the proxy (the browser saves the file). */
export function useReportSnapshotPdfDownload() {
  return useMutation<void, Error, number>({
    mutationFn: async (snapshotId) => {
      const response = await fetch(`/api/proxy/reports/snapshots/${snapshotId}/pdf`, {
        credentials: "include",
      });
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
        `report-${snapshotId}.pdf`,
      );
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  });
}
