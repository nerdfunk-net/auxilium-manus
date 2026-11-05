import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { MAX_TABLE_ROWS, type ParsedTable } from "../utils/parsed-tables";

interface ParsedOutputTablesProps {
  tables: readonly ParsedTable[];
  /** The command output was cut before it was parsed, so a table can be a prefix. */
  incomplete?: boolean;
}

/**
 * Parsed command output as tables, one per command. Cells are plain text (device text is never
 * interpreted as markup); a long table scrolls inside the card.
 */
export function ParsedOutputTables({
  tables,
  incomplete = false,
}: ParsedOutputTablesProps) {
  return (
    <div className="space-y-3" data-testid="device-command-tables">
      {tables.map((table) => (
        <div key={table.command} className="space-y-1">
          <p className="font-mono text-xs text-muted-foreground">
            $ {table.command}
          </p>
          <div className="max-h-72 overflow-auto rounded border">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  {table.columns.map((column) => (
                    <TableHead key={column.key} className="whitespace-nowrap">
                      {column.label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.rows.map((row, rowIndex) => (
                  <TableRow key={rowIndex}>
                    {row.map((text, columnIndex) => (
                      <TableCell
                        key={table.columns[columnIndex].key}
                        className="align-top"
                      >
                        {text}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            {table.totalRows} {table.totalRows === 1 ? "row" : "rows"}
            {table.totalRows > MAX_TABLE_ROWS
              ? `, showing the first ${MAX_TABLE_ROWS}. Download the data for all of them.`
              : ""}
          </p>
        </div>
      ))}
      {incomplete && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="device-command-tables-incomplete"
        >
          The command output was cut because it is very long, so these tables
          may be incomplete.
        </p>
      )}
    </div>
  );
}
