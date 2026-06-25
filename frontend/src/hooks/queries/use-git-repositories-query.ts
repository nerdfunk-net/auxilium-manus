"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface GitRepositoryRecord {
  id: number;
  name: string;
  category: string;
  url: string;
  branch: string;
  is_active: boolean;
  description?: string | null;
}

interface GitRepositoryListResponse {
  repositories: GitRepositoryRecord[];
  total: number;
}

interface UseGitRepositoriesQueryOptions {
  activeOnly?: boolean;
  enabled?: boolean;
}

const DEFAULT_OPTIONS: UseGitRepositoriesQueryOptions = {};

export function useGitRepositoriesQuery(
  options: UseGitRepositoriesQueryOptions = DEFAULT_OPTIONS,
) {
  const { apiCall } = useApi();
  const { activeOnly = true, enabled = true } = options;

  return useQuery({
    queryKey: queryKeys.gitRepositories.list(activeOnly),
    queryFn: async () => {
      const params = activeOnly ? "?active_only=true" : "";
      return apiCall<GitRepositoryListResponse>(`git-repositories${params}`, {
        method: "GET",
      });
    },
    enabled,
    staleTime: 30 * 1000,
  });
}
