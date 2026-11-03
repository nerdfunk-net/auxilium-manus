"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import {
  parsedRowsFileName,
  rowsToCsv,
  rowsToJson,
  saveTextFile,
  type ParsedRow,
} from "../utils/parsed-rows-export";

export type ParsedRowsFormat = "json" | "csv";

interface ParsedRowsResponse {
  parser: string;
  rows: ParsedRow[];
}

export interface ParsedRowsDownloadRequest {
  /** The handle of the parsed rows, as the server made it (`res_` + 12 hex digits). */
  handle: string;
  format: ParsedRowsFormat;
  deviceName: string;
}

const HANDLE = /^res_[0-9a-f]{12}$/;
const MIME: Record<ParsedRowsFormat, string> = {
  json: "application/json",
  csv: "text/csv;charset=utf-8",
};

/**
 * Downloads the full parsed rows of a device command (the card only shows a cut text). The rows
 * are read from the server's short-lived result store, so a handle older than a few hours is
 * refused with a message to run the command again. Not retried.
 */
export function useParsedRowsDownload() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async ({
      handle,
      format,
      deviceName,
    }: ParsedRowsDownloadRequest): Promise<void> => {
      if (!HANDLE.test(handle)) {
        throw new Error("These results cannot be downloaded.");
      }
      const response = await apiCall<ParsedRowsResponse>(
        `ai/results/${handle}/rows`,
        { method: "GET" },
      );
      const text =
        format === "csv" ? rowsToCsv(response.rows) : rowsToJson(response.rows);
      saveTextFile(parsedRowsFileName(deviceName, format), text, MIME[format]);
    },
  });
}
