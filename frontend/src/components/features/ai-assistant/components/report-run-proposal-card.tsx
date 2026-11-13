"use client";

import dynamic from "next/dynamic";
import {
  Download,
  FileText,
  Loader2,
  Play,
  TriangleAlert,
  X,
} from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useReportSnapshotDownload } from "@/hooks/queries/use-report-snapshot-download";

import { useReportGenerateConfirmMutation } from "../hooks/use-report-generate-confirm";
import type { ReportRunProposal, ReportRunResult } from "../types/ai-assistant";

// The viewer pulls in the charts; load it only when a generated report is opened.
const SnapshotViewer = dynamic(
  () =>
    import("@/components/features/reports/components/snapshot-viewer").then(
      (m) => m.SnapshotViewer,
    ),
  { ssr: false },
);

interface ReportRunProposalCardProps {
  proposal: ReportRunProposal;
  onResult: (result: ReportRunResult) => void;
  onReject: () => void;
  /** The assistant is still answering: Generate waits, so the answer can follow it. */
  busy?: boolean;
}

const GENERIC_ERROR = "The report could not be generated";

function isExpired(expiresAt: number): boolean {
  return Date.now() / 1000 >= expiresAt;
}

/**
 * A report the assistant wants generated. Its parts are shown as plain text (never interpreted as
 * markup); the server generates what its signed token says, as the signed-in user, from the data
 * as it is at the click. Nothing is generated until Generate is clicked. The rows of the result
 * go to the user (viewer, PDF, CSV), not through the model.
 */
export function ReportRunProposalCard({
  proposal,
  onResult,
  onReject,
  busy = false,
}: ReportRunProposalCardProps) {
  const { mutateAsync, isPending } = useReportGenerateConfirmMutation();
  const pdf = useReportSnapshotDownload("pdf");
  const csv = useReportSnapshotDownload("csv");
  const [error, setError] = useState<string | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);

  const pending = proposal.state === "pending";
  const expired = pending && isExpired(proposal.expiresAt);
  const result = proposal.result;

  const handleGenerate = async () => {
    if (isExpired(proposal.expiresAt)) {
      setError("This proposal expired. Ask the assistant again.");
      return;
    }
    setError(null);
    try {
      onResult(await mutateAsync(proposal.token));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : GENERIC_ERROR);
    }
  };

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="report-run-proposal"
    >
      <p className="text-sm font-medium">
        Report <span className="font-semibold">{proposal.name}</span>
      </p>
      {proposal.description && (
        <p className="text-xs text-muted-foreground">{proposal.description}</p>
      )}
      <ul className="space-y-0.5 text-xs" aria-label="Sections">
        {proposal.sections.map((section) => (
          <li key={section.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{section.title}</span>
            <span className="font-mono text-muted-foreground">
              {section.source}/{section.dataset}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Layout: {proposal.template ? proposal.template.name : "built-in"}
      </p>

      {pending && (
        <>
          <p className="text-xs text-muted-foreground">
            It is generated as you, with your permissions, from the data as it
            is when you click. You can then open it and download it as PDF or
            CSV.
          </p>
          {expired && (
            <Alert>
              <AlertDescription>
                This proposal expired. Ask the assistant again.
              </AlertDescription>
            </Alert>
          )}
          {busy && !isPending && (
            <p className="text-xs text-muted-foreground">
              Wait until the assistant has finished answering, then generate it.
            </p>
          )}
          {error && !expired && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={handleGenerate}
              disabled={expired || busy || isPending}
            >
              {isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              {isPending ? "Generating…" : "Generate"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onReject}
              disabled={isPending}
            >
              <X className="size-4" />
              Reject
            </Button>
          </div>
        </>
      )}

      {proposal.state === "rejected" && (
        <p className="text-xs text-muted-foreground">
          Rejected. Nothing was generated.
        </p>
      )}

      {result && (
        <div className="space-y-2" data-testid="report-run-generated">
          <p className="text-xs">Generated: {result.name}</p>
          {result.sectionsFailed > 0 && (
            <Alert variant="destructive">
              <TriangleAlert className="size-4" />
              <AlertDescription>
                {result.sectionsFailed === 1
                  ? "One section"
                  : `${result.sectionsFailed} sections`}{" "}
                could not be generated. Open the report to see why.
              </AlertDescription>
            </Alert>
          )}
          {result.status !== "complete" && result.sectionsFailed === 0 && (
            <Alert variant="destructive">
              <TriangleAlert className="size-4" />
              <AlertDescription>
                The data was collected, but the report layout could not be
                applied. Open the report to see why; the data download is still
                complete.
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setViewerOpen(true)}
            >
              <FileText className="size-4" />
              Open
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={pdf.isPending}
              onClick={() => pdf.mutate(result.snapshotId)}
            >
              <Download className="size-4" />
              PDF
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={csv.isPending}
              onClick={() => csv.mutate(result.snapshotId)}
            >
              <Download className="size-4" />
              Data (CSV)
            </Button>
          </div>
          {(pdf.isError || csv.isError) && (
            <p className="text-xs text-destructive">
              {pdf.error?.message ?? csv.error?.message}
            </p>
          )}
          {viewerOpen && (
            <SnapshotViewer
              snapshotId={result.snapshotId}
              onClose={() => setViewerOpen(false)}
            />
          )}
        </div>
      )}
    </div>
  );
}
