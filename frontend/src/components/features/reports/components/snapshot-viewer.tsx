"use client";

import { AlertTriangle, Download, Loader2, Send } from "lucide-react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MarkdownView } from "@/components/ui/markdown-view";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useReportDefinitionQuery } from "@/hooks/queries/use-report-definitions-query";
import { useReportSnapshotPdfDownload } from "@/hooks/queries/use-report-snapshot-pdf-download";
import { useReportSnapshotQuery } from "@/hooks/queries/use-report-snapshots-query";

import type { SnapshotContent } from "../types/report-definition";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { formatTimestamp } from "../utils/format";
import { SendSnapshotDialog } from "./send-snapshot-dialog";

// Recharts is ~270 KB: load it only when a report shows a result (Q5-02).
const SectionResult = dynamic(() => import("./section-result").then((m) => m.SectionResult), {
  ssr: false,
});

const NO_RECIPIENTS: string[] = [];

interface SnapshotViewerProps {
  snapshotId: number | null;
  onClose: () => void;
}

/** A stored report: each section's text and result exactly as they were when generated. */
export function SnapshotViewer({ snapshotId, onClose }: SnapshotViewerProps) {
  const snapshot = useReportSnapshotQuery(snapshotId);
  const data = snapshot.data;
  const canSend = hasPermission(useAuthStore((state) => state.user), "reports", "send");
  const pdf = useReportSnapshotPdfDownload();
  const [sendOpen, setSendOpen] = useState(false);
  // The report the snapshot came from carries the saved recipients (gone if it was deleted).
  const definition = useReportDefinitionQuery(data?.definition_id ?? null);
  const defaultRecipients = definition.data?.default_recipients ?? NO_RECIPIENTS;

  return (
    <Dialog open={snapshotId !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-4 sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>{data?.name ?? "Snapshot"}</DialogTitle>
          <DialogDescription>
            {data
              ? `Generated ${formatTimestamp(data.generated_at)}${data.generated_by ? ` by ${data.generated_by}` : ""}`
              : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {data ? (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={pdf.isPending}
              onClick={() => pdf.mutate(data.id)}
            >
              {pdf.isPending ? (
                <Loader2 className="mr-1 size-4 animate-spin" />
              ) : (
                <Download className="mr-1 size-4" />
              )}
              PDF
            </Button>
            {canSend ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setSendOpen(true)}>
                <Send className="mr-1 size-4" /> Send by email…
              </Button>
            ) : null}
            {pdf.isError ? (
              <span className="text-xs text-destructive">{pdf.error.message}</span>
            ) : null}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto pr-1">
          {snapshot.isLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : null}
          {snapshot.isError ? (
            <Alert variant="destructive">
              <AlertDescription>{snapshot.error.message}</AlertDescription>
            </Alert>
          ) : null}
          {data?.content.body?.error ? (
            <Alert variant="destructive">
              <AlertTriangle className="size-4" />
              <AlertDescription>
                Report text: {data.content.body.error}
              </AlertDescription>
            </Alert>
          ) : null}
          {data?.content.body?.markdown ? (
            <Tabs defaultValue="report">
              <TabsList>
                <TabsTrigger value="report">Report</TabsTrigger>
                <TabsTrigger value="data">Data</TabsTrigger>
              </TabsList>
              <TabsContent value="report" className="pt-3">
                <MarkdownView markdown={data.content.body.markdown} />
              </TabsContent>
              <TabsContent value="data" className="space-y-6 pt-3">
                <SnapshotSections content={data.content} />
              </TabsContent>
            </Tabs>
          ) : data ? (
            <SnapshotSections content={data.content} />
          ) : null}
        </div>
      </DialogContent>
      {data ? (
        <SendSnapshotDialog
          open={sendOpen}
          onOpenChange={setSendOpen}
          snapshotId={data.id}
          snapshotName={data.name}
          defaultRecipients={defaultRecipients}
        />
      ) : null}
    </Dialog>
  );
}

/** Each section's text and result as stored: tables, numbers and charts. */
function SnapshotSections({ content }: { content: SnapshotContent }) {
  return (
    <>
      {content.description ? (
        <p className="text-sm text-muted-foreground">{content.description}</p>
      ) : null}
      {content.sections.map((entry) => (
        <section key={entry.section.id} className="space-y-2">
          <h3 className="text-base font-semibold">{entry.section.title}</h3>
          {entry.section.text ? (
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{entry.section.text}</p>
          ) : null}
          {entry.status === "error" ? (
            <Alert variant="destructive">
              <AlertTriangle className="size-4" />
              <AlertDescription>{entry.error ?? "This section failed."}</AlertDescription>
            </Alert>
          ) : entry.result ? (
            <>
              <SectionResult result={entry.result} presentation={entry.section.presentation} />
              {entry.truncated ? (
                <Badge variant="secondary">More rows matched than are stored here.</Badge>
              ) : null}
            </>
          ) : null}
        </section>
      ))}
    </>
  );
}
