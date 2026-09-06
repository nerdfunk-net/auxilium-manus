"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface GitFileContentParsedResponse {
  parsed: unknown;
  file_path: string;
}

/**
 * Fetch a single file from a Git repository, parsed server-side as YAML/JSON.
 * Backed by `GET /api/git/{repoId}/file-content-parsed?path=<path>`.
 */
export function useGitFileContentParsedQuery(
  repoId: number | null,
  path: string,
  enabled: boolean,
) {
  const { apiCall } = useApi();
  const trimmedPath = path.trim();

  return useQuery({
    queryKey: queryKeys.gitRepositories.fileContentParsed(repoId ?? "none", trimmedPath),
    queryFn: async () =>
      apiCall<GitFileContentParsedResponse>(
        `git/${repoId}/file-content-parsed?path=${encodeURIComponent(trimmedPath)}`,
        { method: "GET" },
      ),
    enabled: enabled && repoId !== null && trimmedPath.length > 0,
    staleTime: 0,
    retry: false,
  });
}
