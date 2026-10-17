"use client";

import { Loader2, Table2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

import type { QueryResult } from "../types/report-query";
import { ResultTable } from "./result-table";

interface ResultPanelProps {
  result: QueryResult | undefined;
  isRunning: boolean;
  errorMessage: string | null;
}

/** The right-hand panel: always fills its column, and only its table body scrolls. */
export function ResultPanel({ result, isRunning, errorMessage }: ResultPanelProps) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <h2 className="text-sm font-semibold">Result</h2>
        {result ? (
          <span className="text-xs text-muted-foreground">
            {result.rows.length} {result.rows.length === 1 ? "row" : "rows"}
          </span>
        ) : null}
        {result?.truncated ? (
          <Badge variant="secondary">More rows matched. Raise the limit or add a filter.</Badge>
        ) : null}
        {isRunning ? <Loader2 className="ml-auto size-4 animate-spin text-muted-foreground" /> : null}
      </div>

      {errorMessage ? (
        <div className="p-4">
          <Alert variant="destructive">
            <AlertDescription>{errorMessage}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      {result ? (
        <div className="min-h-0 flex-1">
          <ResultTable result={result} />
        </div>
      ) : !errorMessage ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-muted-foreground">
          <Table2 className="size-8" />
          <p className="text-sm">Choose a dataset and run a query to see the result here.</p>
        </div>
      ) : null}
    </div>
  );
}
