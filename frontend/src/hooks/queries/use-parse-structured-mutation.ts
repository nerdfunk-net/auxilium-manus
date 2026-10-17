"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export type StructuredFormat = "auto" | "yaml" | "json";

interface ParseStructuredRequest {
  content: string;
  format: StructuredFormat;
}

interface ParseStructuredResponse {
  parsed: unknown;
}

/**
 * Parse a pasted/uploaded YAML or JSON blob server-side.
 * Backed by `POST /api/templates/parse-structured`.
 */
export function useParseStructuredMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: async (request: ParseStructuredRequest) =>
      apiCall<ParseStructuredResponse>("templates/parse-structured", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }),
  });
}
