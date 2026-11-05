/**
 * The parsed output of a device command as tables (the card's `parsedText` is JSON of
 * `[{command, parsed, error}]`). TextFSM gives a list of flat rows per command; that is shown as a
 * table. Anything else (Genie's nested data, a command that did not parse, text that was cut and
 * is no longer valid JSON) is left to the JSON view, never guessed at.
 */

/** What the server appends when it cuts the parsed JSON for the card (`render_text`). */
export const PARSED_TEXT_CUT_MARKER = "…[cut:";

/** Whether the server cut the parsed text, which then is no longer valid JSON. */
export function parsedTextWasCut(parsedText: string): boolean {
  return parsedText.includes(PARSED_TEXT_CUT_MARKER);
}

/** Rows drawn per table; the full data stays behind the handle and the download. */
export const MAX_TABLE_ROWS = 200;

export interface ParsedTableColumn {
  key: string;
  label: string;
}

export interface ParsedTable {
  command: string;
  columns: ParsedTableColumn[];
  /** Cell text per column, in column order. */
  rows: string[][];
  /** Rows the command returned; `rows` holds at most `MAX_TABLE_ROWS` of them. */
  totalRows: number;
}

// Shown first, in this order (CDP/LLDP neighbours); other columns follow in template order.
const PREFERRED_COLUMNS = [
  "local_interface",
  "neighbor_name",
  "neighbor",
  "neighbor_interface",
  "neighbor_port_id",
  "mgmt_address",
  "management_ip",
  "platform",
  "capabilities",
] as const;

const LABELS: Readonly<Record<string, string>> = {
  neighbor_name: "Neighbor",
  neighbor: "Neighbor",
  mgmt_address: "Management IP",
  management_ip: "Management IP",
  neighbor_port_id: "Neighbor port",
};

export function columnLabel(key: string): string {
  const known = LABELS[key];
  if (known) {
    return known;
  }
  const words = key.replace(/_/g, " ").trim();
  // Short upper-case names (AS, VRF) stay as they are.
  if (words === words.toUpperCase()) {
    return words;
  }
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(cellText).join(", ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function isRow(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function orderedKeys(rows: readonly Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      seen.add(key);
    }
  }
  const preferred = PREFERRED_COLUMNS.filter((key) => seen.has(key));
  const rest = [...seen].filter(
    (key) => !(PREFERRED_COLUMNS as readonly string[]).includes(key),
  );
  return [...preferred, ...rest];
}

function tableOf(
  command: string,
  rows: Record<string, unknown>[],
): ParsedTable | null {
  const keys = orderedKeys(rows).filter((key) =>
    rows.some((row) => cellText(row[key]) !== ""),
  );
  if (keys.length === 0) {
    return null;
  }
  return {
    command,
    columns: keys.map((key) => ({ key, label: columnLabel(key) })),
    rows: rows
      .slice(0, MAX_TABLE_ROWS)
      .map((row) => keys.map((key) => cellText(row[key]))),
    totalRows: rows.length,
  };
}

/** One table per command whose parsed data is a list of rows; `[]` when there is none. */
export function parseParsedTables(parsedText: string): ParsedTable[] {
  let data: unknown;
  try {
    data = JSON.parse(parsedText);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) {
    return [];
  }
  const tables: ParsedTable[] = [];
  for (const entry of data) {
    if (!isRow(entry) || typeof entry.command !== "string") {
      continue;
    }
    const parsed = entry.parsed;
    if (!Array.isArray(parsed) || parsed.length === 0 || !parsed.every(isRow)) {
      continue;
    }
    const table = tableOf(entry.command, parsed);
    if (table) {
      tables.push(table);
    }
  }
  return tables;
}
