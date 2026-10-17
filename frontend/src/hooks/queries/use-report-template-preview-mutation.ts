"use client";

import { useMutation } from "@tanstack/react-query";

import type { TemplatePreview } from "@/components/features/reports/types/report-definition";
import { useApi } from "@/hooks/use-api";

interface PreviewInput {
  snapshotId: number;
  content: string;
}

/** Renders unsaved template text against a stored snapshot. Nothing is saved. */
export function useReportTemplatePreviewMutation() {
  const { apiCall } = useApi();
  return useMutation<TemplatePreview, Error, PreviewInput>({
    mutationFn: ({ snapshotId, content }) =>
      apiCall<TemplatePreview>(`reports/snapshots/${snapshotId}/preview-template`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
  });
}
