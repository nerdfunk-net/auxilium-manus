"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export interface GitContentSearchPreviewMatch {
  file_path: string;
  line_content: string;
  hostname: string | null;
  commit: string | null;
}

export interface GitContentSearchPreviewResponse {
  matches: GitContentSearchPreviewMatch[];
  total_matches: number;
  files_scanned: number;
}

interface GitContentSearchPreviewRequest {
  git_repository_id: number;
  directory: string;
  file_filter: string;
  recursive: boolean;
  include_history: boolean;
  search_text: string;
  case_sensitive: boolean;
}

export function useGetFromConfigPreviewMutation() {
  const { apiCall } = useApi();

  return useMutation({
    mutationFn: async (request: GitContentSearchPreviewRequest) => {
      const { git_repository_id, ...body } = request;
      return apiCall<GitContentSearchPreviewResponse>(
        `git/${git_repository_id}/content-search-preview`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
    },
  });
}
