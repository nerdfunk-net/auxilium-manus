"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { useReportQueryMutation } from "@/hooks/queries/use-report-query-mutation";
import { useReportSourcesQuery } from "@/hooks/queries/use-report-sources-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { AddToReportDialog } from "./components/add-to-report-dialog";
import type { ReportQuerySpec } from "./types/report-query";
import { queryToBuilderState } from "./utils/report-sections";

import { QueryBuilder } from "./components/query-builder";
import { ResultPanel } from "./components/result-panel";

const NO_SOURCES: never[] = [];

interface ExploreTabProps {
  /** A query to load into the builder, for example an applied assistant proposal. */
  loadRequest?: { id: number; query: ReportQuerySpec } | null;
}

/** Builder on the left, result on the right (stacked on small screens). */
export function ExploreTab({ loadRequest = null }: ExploreTabProps) {
  const sourcesQuery = useReportSourcesQuery();
  const runQuery = useReportQueryMutation();
  const canWrite = hasPermission(useAuthStore((state) => state.user), "reports", "write");
  const [queryToSave, setQueryToSave] = useState<ReportQuerySpec | null>(null);

  if (sourcesQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (sourcesQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{sourcesQuery.error.message}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-4 lg:h-full lg:min-h-0 lg:flex-row">
      <div className="w-full shrink-0 lg:h-full lg:min-h-0 lg:w-[26rem]">
        <QueryBuilder
          sources={sourcesQuery.data ?? NO_SOURCES}
          isRunning={runQuery.isPending}
          onRun={runQuery.mutate}
          onSave={canWrite ? setQueryToSave : undefined}
          saveLabel="Add to report…"
          key={loadRequest?.id ?? 0}
          initialState={loadRequest ? queryToBuilderState(loadRequest.query) : undefined}
        />
      </div>
      <div className="min-h-[24rem] min-w-0 flex-1 lg:min-h-0">
        <ResultPanel
          result={runQuery.data}
          isRunning={runQuery.isPending}
          errorMessage={runQuery.isError ? runQuery.error.message : null}
        />
      </div>
      <AddToReportDialog query={queryToSave} onClose={() => setQueryToSave(null)} />
    </div>
  );
}
