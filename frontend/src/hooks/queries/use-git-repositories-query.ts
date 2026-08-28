"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export type GitRepositoryAuthType = "none" | "token" | "ssh_key" | "generic";

export interface GitRepositoryRecord {
  id: number;
  name: string;
  category: string;
  url: string;
  branch: string;
  auth_type: GitRepositoryAuthType | null;
  credential_name: string | null;
  path: string | null;
  verify_ssl: boolean;
  git_author_name: string | null;
  git_author_email: string | null;
  description?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_sync: string | null;
  sync_status: string | null;
}

interface GitRepositoryListResponse {
  repositories: GitRepositoryRecord[];
  total: number;
}

interface UseGitRepositoriesQueryOptions {
  activeOnly?: boolean;
  category?: string;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseGitRepositoriesQueryOptions = {};

export function useGitRepositoriesQuery(
  options: UseGitRepositoriesQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { activeOnly = true, category, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.gitRepositories.list(activeOnly, category),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeOnly) params.set("active_only", "true");
      if (category) params.set("category", category);
      const query = params.toString();
      return apiCall<GitRepositoryListResponse>(
        `git-repositories${query ? `?${query}` : ""}`,
        { method: "GET" },
      );
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
