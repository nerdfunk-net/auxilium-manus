"use client";

import { Pencil, RefreshCw, RotateCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { GitRepositoryRecord } from "@/hooks/queries/use-git-repositories-query";

import { GitRepositoryCategoryBadge } from "./git-repository-category-badge";
import { GitRepositoryStatusBadge } from "./git-repository-status-badge";
import { formatLastSync, gitAuthTypeLabel } from "../utils/git-repository-utils";

interface GitRepositoriesTableProps {
  repositories: GitRepositoryRecord[];
  isSyncing: boolean;
  isRemovingAndCloning: boolean;
  onSync: (repository: GitRepositoryRecord) => void;
  onRemoveAndClone: (repository: GitRepositoryRecord) => void;
  onEdit: (repository: GitRepositoryRecord) => void;
  onDelete: (repository: GitRepositoryRecord) => void;
}

export function GitRepositoriesTable({
  repositories,
  isSyncing,
  isRemovingAndCloning,
  onSync,
  onRemoveAndClone,
  onEdit,
  onDelete,
}: GitRepositoriesTableProps) {
  if (repositories.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        No Git repositories configured yet.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {repositories.map((repository) => (
        <li
          key={repository.id}
          className="grid gap-3 rounded-lg border bg-background px-4 py-3 md:grid-cols-[1.6fr_9rem_10rem_10rem_auto] md:items-center"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate font-mono text-sm font-medium">{repository.name}</p>
              <GitRepositoryStatusBadge isActive={repository.is_active} />
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground">{repository.url}</p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Category
            </p>
            <GitRepositoryCategoryBadge category={repository.category} className="mt-1" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Branch / Auth
            </p>
            <p className="truncate text-sm">{repository.branch}</p>
            <p className="truncate text-xs text-muted-foreground">
              {gitAuthTypeLabel(repository.auth_type)}
              {repository.credential_name ? ` · ${repository.credential_name}` : ""}
            </p>
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Last sync
            </p>
            <p className="truncate text-sm">{repository.sync_status ?? "—"}</p>
            <p className="truncate text-xs text-muted-foreground">
              {formatLastSync(repository.last_sync)}
            </p>
          </div>
          <div className="flex items-center justify-end gap-1">
            <Button
              aria-label={`Sync ${repository.name}`}
              size="icon"
              type="button"
              variant="ghost"
              disabled={isSyncing}
              onClick={() => onSync(repository)}
              title="Sync (clone if missing, pull if present)"
            >
              <RotateCcw className="size-4" />
            </Button>
            <Button
              aria-label={`Remove and re-clone ${repository.name}`}
              size="icon"
              type="button"
              variant="ghost"
              disabled={isRemovingAndCloning}
              onClick={() => onRemoveAndClone(repository)}
              title="Remove local copy and re-clone"
            >
              <RefreshCw className="size-4" />
            </Button>
            <Button
              aria-label={`Edit ${repository.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onEdit(repository)}
            >
              <Pencil className="size-4" />
            </Button>
            <Button
              aria-label={`Delete ${repository.name}`}
              size="icon"
              type="button"
              variant="ghost"
              onClick={() => onDelete(repository)}
            >
              <Trash2 className="size-4 text-destructive" />
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
