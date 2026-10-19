"use client";

import { useGitRepositoriesQuery } from "@/hooks/queries/use-git-repositories-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

const WORKFLOW_REPOSITORIES = { activeOnly: true, category: "workflows" } as const;

/**
 * Whether a git repository is configured for workflows. A user without
 * `git.repositories:read` would only get a 403, so the request is not made.
 */
export function useWorkflowGitRepositories() {
  const canRead = useAuthStore((state) =>
    hasPermission(state.user, "git.repositories", "read"),
  );
  const { data } = useGitRepositoriesQuery({ ...WORKFLOW_REPOSITORIES, enabled: canRead });
  return { hasConfiguredGitRepository: (data?.repositories.length ?? 0) > 0 };
}
