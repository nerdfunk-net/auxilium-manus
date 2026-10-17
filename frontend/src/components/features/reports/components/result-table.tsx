"use client";

import { TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import type { QueryResult } from "../types/report-query";
import { formatCell } from "../utils/query-spec";

interface ResultTableProps {
  result: QueryResult;
}

/**
 * Fills its parent and scrolls both ways inside it, with a sticky header. A plain <table> is
 * used on purpose: the shared Table wraps itself in another overflow container, which would
 * stop the header from sticking.
 */
export function ResultTable({ result }: ResultTableProps) {
  return (
    <div className="h-full overflow-auto">
      <table className="w-full caption-bottom text-sm">
        <TableHeader className="sticky top-0 z-10 bg-muted">
          <TableRow className="hover:bg-muted">
            {result.columns.map((column) => (
              <TableHead
                key={column.key}
                className={cn(
                  "whitespace-nowrap font-mono text-xs",
                  column.type === "number" && "text-right",
                )}
              >
                {column.label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={Math.max(result.columns.length, 1)}
                className="py-8 text-center text-sm text-muted-foreground"
              >
                No rows match.
              </TableCell>
            </TableRow>
          ) : (
            result.rows.map((row, rowIndex) => (
              <TableRow key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <TableCell
                    key={cellIndex}
                    className={cn(
                      "whitespace-nowrap font-mono text-xs",
                      result.columns[cellIndex]?.type === "number" && "text-right tabular-nums",
                    )}
                  >
                    {formatCell(cell)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </table>
    </div>
  );
}
