export type ParsedRow = Record<string, unknown>;

/** The rows as indented JSON. */
export function rowsToJson(rows: readonly ParsedRow[]): string {
  return JSON.stringify(rows, null, 2);
}

const NUMBER = /^[-+]?\d+(\.\d+)?$/;
// A cell starting with one of these is run as a formula by spreadsheet programs.
const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  let text = typeof value === "string" ? value : JSON.stringify(value);
  if (
    typeof value === "string" &&
    FORMULA_START.test(text) &&
    !NUMBER.test(text)
  ) {
    text = `'${text}`;
  }
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function columnsOf(rows: readonly ParsedRow[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      seen.add(key);
    }
  }
  // The command column leads, the rest keep the order they first appear in.
  const rest = [...seen].filter((key) => key !== "_command");
  return seen.has("_command") ? ["_command", ...rest] : rest;
}

/** The rows as CSV (RFC 4180 quoting, CRLF). Nested values are written as JSON. */
export function rowsToCsv(rows: readonly ParsedRow[]): string {
  if (rows.length === 0) {
    return "";
  }
  const columns = columnsOf(rows);
  const lines = [
    columns.map(cell).join(","),
    ...rows.map((row) => columns.map((column) => cell(row[column])).join(",")),
  ];
  return lines.join("\r\n");
}

/** `<device>-parsed.<ext>`, with the device reduced to a safe slug. */
export function parsedRowsFileName(
  deviceName: string,
  extension: "json" | "csv",
): string {
  const slug =
    deviceName
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "device";
  return `${slug}-parsed.${extension}`;
}

/** Offers `text` to the browser as a file download. */
export function saveTextFile(name: string, text: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
