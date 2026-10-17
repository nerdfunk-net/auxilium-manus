import type { ReactNode } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ColumnDiff, TableColumnRef } from "@/hooks/queries/use-schema-query";

export function SchemaSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </div>
  );
}

export function RefTable({ rows, columnLabel }: { rows: TableColumnRef[]; columnLabel: string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Table</TableHead>
          <TableHead>{columnLabel}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={`${row.table}.${row.column}`}>
            <TableCell className="font-mono text-xs">{row.table}</TableCell>
            <TableCell className="font-mono text-xs">{row.column}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function DiffTable({ diffs }: { diffs: ColumnDiff[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Table</TableHead>
          <TableHead>Column</TableHead>
          <TableHead>Change</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {diffs.map((diff) => (
          <TableRow key={`${diff.table}.${diff.column}`}>
            <TableCell className="font-mono text-xs">{diff.table}</TableCell>
            <TableCell className="font-mono text-xs">{diff.column}</TableCell>
            <TableCell className="font-mono text-xs">
              {diff.type_changed && (
                <div>
                  {diff.db_type} → {diff.model_type}
                </div>
              )}
              {diff.nullable_changed && (
                <div>
                  {diff.db_nullable ? "NULL" : "NOT NULL"} → {diff.model_nullable ? "NULL" : "NOT NULL"}
                </div>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
