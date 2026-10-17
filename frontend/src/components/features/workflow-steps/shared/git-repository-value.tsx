"use client";

import { useMemo } from "react";

import { useGitRepositoriesQuery } from "@/hooks/queries/use-git-repositories-query";

/**
 * Resolves a configured `git_repository_id` to a human-readable label of the form
 * `my repo (1)`. Returns `null` when `repositoryId` is `null`. While the
 * repository list is still loading an unresolved id renders as `Repository 1…`;
 * once loaded, an id with no matching repository renders as
 * `Repository 1 — not found`.
 */
export function useGitRepositoryLabel(repositoryId: number | null): string | null {
  const { data, isLoading } = useGitRepositoriesQuery({ activeOnly: false });

  return useMemo(() => {
    if (repositoryId === null) {
      return null;
    }
    const match = data?.repositories.find((repo) => repo.id === repositoryId);
    if (match) {
      return `${match.name} (${match.id})`;
    }
    if (isLoading) {
      return `Repository ${repositoryId}…`;
    }
    return `Repository ${repositoryId} — not found`;
  }, [data, isLoading, repositoryId]);
}

interface GitRepositoryValueProps {
  /** The configured `git_repository_id`, or `null` when the step has none yet. */
  repositoryId: number | null;
}

/**
 * Renders the human-readable name of a configured Git repository followed by its
 * id in parentheses (e.g. `my repo (1)`), instead of showing the bare numeric id.
 */
export function GitRepositoryValue({ repositoryId }: GitRepositoryValueProps) {
  const label = useGitRepositoryLabel(repositoryId);

  if (label === null) {
    return <p className="text-[11px] text-warning-foreground">Not configured</p>;
  }

  return <p className="text-[11px] text-muted-foreground">{label}</p>;
}
