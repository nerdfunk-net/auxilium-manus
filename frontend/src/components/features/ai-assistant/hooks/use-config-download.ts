"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

import { RESULT_HANDLE, configFileName } from "../utils/config-download";
import { saveTextFile } from "../utils/parsed-rows-export";

interface ConfigTextResponse {
  device: string;
  kind: string;
  committed_at: string | null;
  text: string;
}

export interface ConfigDownloadRequest {
  /** The handle of the stored config, as the server made it. */
  handle: string;
}

/**
 * Downloads a backed-up config (the chat only shows a preview). The text is read from the server's
 * short-lived result store, so a handle older than a few hours is refused; the user then asks the
 * assistant again. Not retried.
 */
export function useConfigDownload() {
  const { apiCall } = useApi();

  return useMutation({
    retry: false,
    mutationFn: async ({ handle }: ConfigDownloadRequest): Promise<void> => {
      if (!RESULT_HANDLE.test(handle)) {
        throw new Error("This configuration cannot be downloaded.");
      }
      const response = await apiCall<ConfigTextResponse>(
        `ai/results/${handle}/text`,
        { method: "GET" },
      );
      saveTextFile(
        configFileName(response.device, response.kind),
        response.text,
        "text/plain;charset=utf-8",
      );
    },
  });
}
