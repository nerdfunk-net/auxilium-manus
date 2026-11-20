"use client";

import { Download } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  isRetryableCompareError,
  useCompareResultQuery,
} from "../hooks/use-compare-result-query";
import type { CompareResultProposal } from "../types/ai-assistant";
import {
  compareCsv,
  compareFileName,
  fieldLabel,
  splitSides,
  usedFileColumns,
  visibleRows,
  type CompareResultData,
  type CompareRow,
} from "../utils/compare-result";
import { saveTextFile } from "../utils/parsed-rows-export";

const MAX_FILE_TABLE_COLUMNS = 3;

interface CompareResultCardProps {
  proposal: CompareResultProposal;
}

interface SideListProps {
  testId: string;
  title: string;
  rows: readonly CompareRow[];
  limit: number;
  columns: readonly string[];
  kind: "file" | "both" | "device";
}

function SideList({ testId, title, rows, limit, columns, kind }: SideListProps) {
  const { shown, hidden } = visibleRows(rows, limit);
  // The columns come from the whole list, not the sample: a column filled only in later rows
  // still gets its place.
  const fileColumns =
    kind !== "device" ? usedFileColumns(rows, columns, MAX_FILE_TABLE_COLUMNS) : [];
  return (
    <section className="space-y-1" data-testid={testId}>
      <p className="text-xs font-medium">
        {title} <span className="text-muted-foreground">({rows.length})</span>
      </p>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">None.</p>
      ) : (
        <>
          <div className="max-h-64 overflow-auto rounded border">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  {kind !== "device" ? (
                    <>
                      <TableHead>Value</TableHead>
                      {fileColumns.map((name) => (
                        <TableHead key={name}>{name}</TableHead>
                      ))}
                      {kind === "both" && (
                        <>
                          <TableHead>Device</TableHead>
                          <TableHead>Location</TableHead>
                        </>
                      )}
                    </>
                  ) : (
                    <>
                      {rows[0]?.side === "without_value" ? null : <TableHead>Value</TableHead>}
                      <TableHead>Device</TableHead>
                      <TableHead>Location</TableHead>
                    </>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((row, index) => (
                  <TableRow key={index}>
                    {kind !== "device" ? (
                      <>
                        <TableCell className="font-mono">{row.value}</TableCell>
                        {fileColumns.map((name) => (
                          <TableCell key={name}>{row.fileValues[name] ?? ""}</TableCell>
                        ))}
                        {kind === "both" && (
                          <>
                            <TableCell>{row.deviceName}</TableCell>
                            <TableCell>{row.deviceLocation}</TableCell>
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        {row.side === "without_value" ? null : (
                          <TableCell className="font-mono">{row.value}</TableCell>
                        )}
                        <TableCell>{row.deviceName}</TableCell>
                        <TableCell>{row.deviceLocation}</TableCell>
                      </>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {hidden > 0 && (
            <p className="text-xs text-muted-foreground">
              Showing the first {shown.length} of {rows.length}. The download has all of them.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function Lists({
  data,
  proposal,
}: {
  data: CompareResultData;
  proposal: CompareResultProposal;
}) {
  const sides = splitSides(data.rows);
  const limit = proposal.inlineLimit;
  return (
    <div className="space-y-3">
      <SideList
        testId="compare-only-in-file"
        title="In the file, not in Nautobot"
        rows={sides.onlyInFile}
        limit={limit}
        columns={data.columns}
        kind="file"
      />
      <SideList
        testId="compare-in-both"
        title="In the file and in Nautobot"
        rows={sides.inBoth}
        limit={limit}
        columns={data.columns}
        kind="both"
      />
      <SideList
        testId="compare-only-in-nautobot"
        title="In Nautobot, not in the file"
        rows={sides.onlyInNautobot}
        limit={limit}
        columns={data.columns}
        kind="device"
      />
      {sides.withoutValue.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs font-medium">
            Devices without a value in Nautobot (not compared) ({sides.withoutValue.length})
          </summary>
          <div className="mt-1">
            <SideList
              testId="compare-without-value"
              title="Not compared"
              rows={sides.withoutValue}
              limit={limit}
              columns={data.columns}
              kind="device"
            />
          </div>
        </details>
      )}
    </div>
  );
}

/**
 * The result of comparing a file with Nautobot. The assistant only knows the counts; the lists are
 * fetched here as the signed-in user. Everything shown is plain text (never markup).
 */
export function CompareResultCard({ proposal }: CompareResultCardProps) {
  const query = useCompareResultQuery(proposal.handle);
  const { counts } = proposal;
  const data = query.data;

  return (
    <div className="space-y-2 rounded-md border bg-card p-3" data-testid="compare-result-card">
      <p className="text-sm font-medium">
        {fieldLabel(proposal.nautobotField)} in Nautobot compared with column{" "}
        <span className="font-mono font-semibold">{proposal.keyColumn}</span> of{" "}
        <span className="font-semibold">{proposal.file}</span>
      </p>
      <p className="text-xs text-muted-foreground">
        Repository {proposal.repository}.{" "}
        {proposal.matchMode === "contains" ? "The Nautobot value contains the file value" : "Equal values"}
        {proposal.caseInsensitive ? ", ignoring case" : ""}. The assistant was given the counts only,
        never the values.
      </p>
      <div className="flex flex-wrap gap-1.5" data-testid="compare-counts">
        <Badge variant="outline">In file only: {counts.only_in_file ?? 0}</Badge>
        <Badge variant="outline">In Nautobot only: {counts.only_in_nautobot ?? 0}</Badge>
        <Badge variant="outline">In both: {counts.matched_keys ?? 0}</Badge>
        {(counts.devices_without_value ?? 0) > 0 && (
          <Badge variant="outline">Without a value: {counts.devices_without_value}</Badge>
        )}
      </div>
      {query.isLoading && <p className="text-xs text-muted-foreground">Loading the lists…</p>}
      {query.error && (
        <Alert variant="destructive">
          <AlertDescription>{query.error.message}</AlertDescription>
        </Alert>
      )}
      {query.error && isRetryableCompareError(query.error) && (
        <Button type="button" size="sm" variant="outline" onClick={() => void query.refetch()}>
          Try again
        </Button>
      )}
      {data && <Lists data={data} proposal={proposal} />}
      {(proposal.partial || data?.partial) && (
        <p className="text-xs text-muted-foreground" data-testid="compare-partial">
          The lists were cut to fit the size limit of a stored result. The counts above are exact.
        </p>
      )}
      {data && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() =>
            saveTextFile(compareFileName(data.file), compareCsv(data), "text/csv;charset=utf-8")
          }
        >
          <Download className="size-4" />
          Download CSV
        </Button>
      )}
      <p className="text-xs text-muted-foreground">
        The lists are kept for a few hours; this card is gone once you reload the page or reopen the
        chat.
      </p>
    </div>
  );
}
