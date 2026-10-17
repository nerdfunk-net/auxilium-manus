"use client";

import { useMutation } from "@tanstack/react-query";

import type {
  SendSnapshotInput,
  SendSnapshotResult,
} from "@/components/features/reports/types/report-definition";
import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";

/** Mails a stored snapshot (needs `reports:send` and configured mail settings). */
export function useReportSnapshotSendMutation() {
  const { apiCall } = useApi();
  const { toast } = useToast();
  return useMutation<SendSnapshotResult, Error, { snapshotId: number; input: SendSnapshotInput }>({
    mutationFn: ({ snapshotId, input }) =>
      apiCall<SendSnapshotResult>(`reports/snapshots/${snapshotId}/send`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: (result) =>
      toast({
        title: "Report sent",
        description: `Sent to ${result.sent_to.length} recipient(s)${result.pdf_attached ? " with a PDF" : ""}.`,
      }),
  });
}
