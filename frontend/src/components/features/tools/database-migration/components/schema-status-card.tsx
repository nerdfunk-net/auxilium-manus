"use client";

import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";
import { useMemo } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SchemaMigrationResult } from "@/hooks/queries/use-schema-mutations";
import type { SchemaStatus } from "@/hooks/queries/use-schema-query";

import { DiffTable, RefTable, SchemaSection } from "./schema-diff-tables";

interface SchemaStatusCardProps {
  status: SchemaStatus | undefined;
  isLoading: boolean;
  isFetching: boolean;
  onRefresh: () => void;
  migrationResult: SchemaMigrationResult | null;
  isMigrating: boolean;
  canWrite: boolean;
  onSync: () => void;
  onForceApplyClick: () => void;
}

export function SchemaStatusCard({
  status,
  isLoading,
  isFetching,
  onRefresh,
  migrationResult,
  isMigrating,
  canWrite,
  onSync,
  onForceApplyClick,
}: SchemaStatusCardProps) {
  const safeDiffs = useMemo(() => status?.column_diffs.filter((d) => d.safe) ?? [], [status]);
  const riskyDiffs = useMemo(() => status?.column_diffs.filter((d) => !d.safe) ?? [], [status]);

  const hasSafeChanges =
    !!status &&
    (status.missing_tables.length > 0 ||
      status.missing_columns.length > 0 ||
      status.missing_indexes.length > 0 ||
      safeDiffs.length > 0);

  const hasExtraItems =
    !!status &&
    (status.extra_tables.length > 0 || status.extra_columns.length > 0 || status.extra_indexes.length > 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base">Schema Status</CardTitle>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isFetching}>
          {isFetching ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 size-4" />
          )}
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading || !status ? (
          <p className="text-sm text-muted-foreground">Loading schema status…</p>
        ) : (
          <>
            {status.is_up_to_date ? (
              <Alert variant="success">
                <CheckCircle2 />
                <AlertTitle>Schema is in sync</AlertTitle>
                <AlertDescription>The database matches the current models.</AlertDescription>
              </Alert>
            ) : (
              <Alert variant="warning">
                <AlertTriangle />
                <AlertTitle>Schema differences detected</AlertTitle>
                <AlertDescription>
                  {status.missing_tables.length} missing table(s), {status.missing_columns.length}{" "}
                  missing column(s), {status.column_diffs.length} column change(s),{" "}
                  {status.missing_indexes.length} missing index(es).
                </AlertDescription>
              </Alert>
            )}

            {status.missing_tables.length > 0 && (
              <SchemaSection title="Missing Tables">
                <div className="flex flex-wrap gap-2">
                  {status.missing_tables.map((t) => (
                    <Badge key={t} variant="secondary">
                      {t}
                    </Badge>
                  ))}
                </div>
              </SchemaSection>
            )}

            {status.missing_columns.length > 0 && (
              <SchemaSection title="Missing Columns">
                <RefTable rows={status.missing_columns} columnLabel="Column" />
              </SchemaSection>
            )}

            {status.missing_indexes.length > 0 && (
              <SchemaSection title="Missing Indexes">
                <RefTable
                  rows={status.missing_indexes.map((i) => ({ table: i.table, column: i.index }))}
                  columnLabel="Index"
                />
              </SchemaSection>
            )}

            {safeDiffs.length > 0 && (
              <SchemaSection title="Safe Column Changes">
                <DiffTable diffs={safeDiffs} />
              </SchemaSection>
            )}

            {riskyDiffs.length > 0 && (
              <SchemaSection title="Risky Column Changes">
                <Alert variant="destructive" className="mb-3">
                  <AlertTriangle />
                  <AlertTitle>Force required</AlertTitle>
                  <AlertDescription>
                    These changes may cause data loss and are never applied automatically. Set{" "}
                    <code>APPLY_RISKY_DATABASE_MIGRATION=true</code> to apply on startup, or run{" "}
                    <code>python scripts/database/sync.py --migrate --force</code>.
                  </AlertDescription>
                </Alert>
                <DiffTable diffs={riskyDiffs} />
              </SchemaSection>
            )}

            {hasExtraItems && (
              <SchemaSection title="Extra items in database (informational only)">
                <div className="space-y-1 text-sm text-muted-foreground">
                  {status.extra_tables.map((t) => (
                    <div key={t}>Table: {t}</div>
                  ))}
                  {status.extra_columns.map((c) => (
                    <div key={`${c.table}.${c.column}`}>
                      Column: {c.table}.{c.column}
                    </div>
                  ))}
                  {status.extra_indexes.map((i) => (
                    <div key={`${i.table}.${i.index}`}>
                      Index: {i.index} (on {i.table})
                    </div>
                  ))}
                </div>
              </SchemaSection>
            )}

            {!status.is_up_to_date && (
              <div className="flex justify-end gap-2 pt-2">
                {riskyDiffs.length > 0 && (
                  <Button
                    variant="destructive"
                    disabled={!canWrite || isMigrating}
                    onClick={onForceApplyClick}
                  >
                    Force Apply ({riskyDiffs.length} risky)
                  </Button>
                )}
                <Button disabled={!canWrite || !hasSafeChanges || isMigrating} onClick={onSync}>
                  {isMigrating && <Loader2 className="mr-2 size-4 animate-spin" />}
                  Sync Schema
                </Button>
              </div>
            )}
          </>
        )}

        {migrationResult && (
          <Alert variant={migrationResult.success ? "success" : "destructive"}>
            <AlertTitle>{migrationResult.message}</AlertTitle>
            <AlertDescription className="space-y-1">
              <div>
                {migrationResult.tables_created} table(s) created, {migrationResult.columns_added}{" "}
                column(s) added, {migrationResult.indexes_created} index(es) created.
              </div>
              {migrationResult.column_changes_applied.length > 0 && (
                <div>Applied: {migrationResult.column_changes_applied.join(", ")}</div>
              )}
              {migrationResult.column_changes_skipped.length > 0 && (
                <div>Skipped: {migrationResult.column_changes_skipped.join(", ")}</div>
              )}
              {migrationResult.errors.length > 0 && (
                <div className="text-destructive">{migrationResult.errors.join(", ")}</div>
              )}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
