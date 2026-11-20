import { RESULT_HANDLE } from "./config-download";
import { rowsToCsv, type ParsedRow } from "./parsed-rows-export";

/** Rows shown per side when a list is longer than the inline limit. */
export const SAMPLE_ROWS = 10;
export const DEFAULT_INLINE_LIMIT = 50;

export type CompareSide = "only_in_file" | "in_both" | "only_in_nautobot" | "without_value";
const SIDES: readonly CompareSide[] = [
  "only_in_file",
  "in_both",
  "only_in_nautobot",
  "without_value",
];

const FIELD_LABELS: Record<string, string> = {
  serial: "serial number",
  name: "device name",
  primary_ip4: "primary IPv4 address",
  location: "location",
  software_version: "software version",
};

/** A readable name for a Nautobot field (unknown names are shown as they are). */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

export interface CompareRow {
  side: CompareSide;
  value: string;
  deviceName: string;
  deviceLocation: string;
  /** The file's other columns, by header name, empty cells left out. */
  fileValues: Record<string, string>;
}

export interface CompareResultData {
  repository: string;
  file: string;
  keyColumn: string;
  nautobotField: string;
  matchMode: string;
  caseInsensitive: boolean;
  counts: Record<string, number>;
  columns: string[];
  partial: boolean;
  rows: CompareRow[];
  /** The rows as the server stored them, for the CSV download. */
  rawRows: ParsedRow[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  return typeof value === "string" ? value : String(value);
}

function numberMap(value: unknown): Record<string, number> {
  const result: Record<string, number> = {};
  if (isRecord(value)) {
    for (const [key, item] of Object.entries(value)) {
      result[key] = typeof item === "number" && Number.isFinite(item) ? item : 0;
    }
  }
  return result;
}

function toRow(raw: ParsedRow): CompareRow | null {
  const side = SIDES.find((candidate) => candidate === raw.side);
  if (!side) {
    return null;
  }
  const fileValues: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (key.startsWith("file_") && text(value) !== "") {
      fileValues[key.slice("file_".length)] = text(value);
    }
  }
  return {
    side,
    value: text(raw.value),
    deviceName: text(raw.device_name),
    deviceLocation: text(raw.device_location),
    fileValues,
  };
}

/** The server's answer, or null when anything the card needs is missing or mistyped. */
export function parseCompareResponse(raw: unknown): CompareResultData | null {
  if (!isRecord(raw) || !Array.isArray(raw.rows) || !isRecord(raw.counts)) {
    return null;
  }
  const rawRows = raw.rows.filter(isRecord);
  const rows = rawRows.map(toRow).filter((row): row is CompareRow => row !== null);
  return {
    repository: text(raw.repository),
    file: text(raw.file),
    keyColumn: text(raw.key_column),
    nautobotField: text(raw.nautobot_field),
    matchMode: text(raw.match_mode),
    caseInsensitive: raw.case_insensitive === true,
    counts: numberMap(raw.counts),
    columns: Array.isArray(raw.columns) ? raw.columns.map(text) : [],
    partial: raw.partial === true,
    rows,
    rawRows,
  };
}

export interface ComparedSides {
  onlyInFile: CompareRow[];
  inBoth: CompareRow[];
  onlyInNautobot: CompareRow[];
  withoutValue: CompareRow[];
}

export function splitSides(rows: readonly CompareRow[]): ComparedSides {
  return {
    onlyInFile: rows.filter((row) => row.side === "only_in_file"),
    inBoth: rows.filter((row) => row.side === "in_both"),
    onlyInNautobot: rows.filter((row) => row.side === "only_in_nautobot"),
    withoutValue: rows.filter((row) => row.side === "without_value"),
  };
}

/**
 * The rows a list shows: all of them up to `limit` (the server's inline limit), otherwise only a
 * sample and the number left out (the download has every row).
 */
export function visibleRows<T>(
  rows: readonly T[],
  limit: number,
): { shown: T[]; hidden: number } {
  if (rows.length <= limit) {
    return { shown: [...rows], hidden: 0 };
  }
  const count = Math.min(SAMPLE_ROWS, limit);
  return { shown: rows.slice(0, count), hidden: rows.length - count };
}

/** The file columns worth a table column: the first `max` that hold a value in `rows`. */
export function usedFileColumns(
  rows: readonly CompareRow[],
  columns: readonly string[],
  max: number,
): string[] {
  return columns.filter((name) => rows.some((row) => name in row.fileValues)).slice(0, max);
}

/** `<file-name>-compare.csv`, reduced to a safe slug. */
export function compareFileName(file: string): string {
  const base = file.split("/").pop() ?? file;
  const slug =
    base
      .replace(/\.[a-z0-9]+$/i, "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "file";
  return `${slug}-compare.csv`;
}

/** The CSV for the download: every stored row; a byte order mark so a spreadsheet reads UTF-8. */
export function compareCsv(data: CompareResultData): string {
  return `﻿${rowsToCsv(data.rawRows)}`;
}

export type CompareProposalData = {
  handle: string;
  repository: string;
  file: string;
  keyColumn: string;
  nautobotField: string;
  matchMode: "match" | "contains";
  caseInsensitive: boolean;
  counts: Record<string, number>;
  partial: boolean;
  inlineLimit: number;
};

/** The proposal payload of a comparison, or null when the card cannot be built from it. */
export function parseCompareProposal(source: object): CompareProposalData | null {
  const payload = source as Record<string, unknown>;
  const handle = payload.handle;
  if (typeof handle !== "string" || !RESULT_HANDLE.test(handle) || !isRecord(payload.counts)) {
    return null;
  }
  const limit = payload.inline_limit;
  return {
    handle,
    repository: text(payload.repository),
    file: text(payload.file),
    keyColumn: text(payload.key_column),
    nautobotField: text(payload.nautobot_field),
    matchMode: payload.match_mode === "contains" ? "contains" : "match",
    caseInsensitive: payload.case_insensitive === true,
    counts: numberMap(payload.counts),
    partial: payload.partial === true,
    inlineLimit:
      typeof limit === "number" && Number.isFinite(limit) && limit > 0
        ? Math.floor(limit)
        : DEFAULT_INLINE_LIMIT,
  };
}
