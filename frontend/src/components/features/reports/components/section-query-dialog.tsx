"use client";

import { useCallback } from "react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useReportQueryMutation } from "@/hooks/queries/use-report-query-mutation";
import { useReportSourcesQuery } from "@/hooks/queries/use-report-sources-query";

import type { ReportQuerySpec } from "../types/report-query";
import { queryToBuilderState } from "../utils/report-sections";
import { QueryBuilder } from "./query-builder";
import { ResultPanel } from "./result-panel";

const NO_SOURCES: never[] = [];

interface SectionQueryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The section's current query; undefined starts an empty builder (new section). */
  query?: ReportQuerySpec;
  onSave: (query: ReportQuerySpec) => void;
}

/** The query builder with a live preview, used to define or change one report section. */
export function SectionQueryDialog({ open, onOpenChange, query, onSave }: SectionQueryDialogProps) {
  const sources = useReportSourcesQuery();
  const preview = useReportQueryMutation();
  const handleSave = useCallback(
    (next: ReportQuerySpec) => {
      onSave(next);
      onOpenChange(false);
    },
    [onOpenChange, onSave],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Section query</DialogTitle>
          <DialogDescription>Build the query, check the preview, then use it for this section.</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row lg:overflow-hidden">
          <div className="w-full shrink-0 lg:h-full lg:min-h-0 lg:w-[26rem]">
            <QueryBuilder
              sources={sources.data ?? NO_SOURCES}
              isRunning={preview.isPending}
              onRun={preview.mutate}
              initialState={query ? queryToBuilderState(query) : undefined}
              onSave={handleSave}
              saveLabel="Use this query"
            />
          </div>
          <div className="min-h-[20rem] min-w-0 flex-1 lg:min-h-0">
            <ResultPanel
              result={preview.data}
              isRunning={preview.isPending}
              errorMessage={preview.isError ? preview.error.message : null}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
