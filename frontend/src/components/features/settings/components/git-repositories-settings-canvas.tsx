"use client";

import { useState } from "react";
import { GitBranch, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useGitRepositoriesMutations } from "@/hooks/queries/use-git-repositories-mutations";
import {
  useGitRepositoriesQuery,
  type GitRepositoryRecord,
} from "@/hooks/queries/use-git-repositories-query";

import { GitRepositoryDialog } from "../dialogs/git-repository-dialog";

export function GitRepositoriesSettingsCanvas() {
  const { data, isLoading, error } = useGitRepositoriesQuery({ activeOnly: false });
  const { deleteRepository, syncRepository, removeAndSyncRepository } =
    useGitRepositoriesMutations();

  const [editing, setEditing] = useState<GitRepositoryRecord | null | undefined>(undefined);
  const [deleteTarget, setDeleteTarget] = useState<GitRepositoryRecord | null>(null);
  const [removeAndCloneTarget, setRemoveAndCloneTarget] = useState<GitRepositoryRecord | null>(
    null,
  );

  const repositories = data?.repositories ?? [];

  return (
    <>
      <div className="flex h-full flex-col overflow-y-auto bg-muted p-10">
        <div className="mx-auto w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
          <div className="mb-6 flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <GitBranch className="size-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">Git Repositories</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Repositories used by git-clone / git-pull / git-push / get-git-devices and other
                workflow steps, plus (if one is marked &quot;Workflow version control&quot;) the
                workflow Manage dialog. Each repository supports token or SSH-key auth via
                Settings → Credentials.
              </p>
            </div>
            <Button type="button" onClick={() => setEditing(null)}>
              <Plus className="size-4" />
              Add repository
            </Button>
          </div>

          <div className="rounded-xl border border-dashed bg-muted/30 p-6">
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : error ? (
              <p className="text-sm text-destructive">
                Failed to load Git repositories: {error.message}
              </p>
            ) : repositories.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <p className="text-sm text-muted-foreground">No Git repositories configured yet.</p>
                <Button type="button" onClick={() => setEditing(null)}>
                  Add repository
                </Button>
              </div>
            ) : (
              <ul className="space-y-2">
                {repositories.map((repository) => (
                  <li
                    key={repository.id}
                    className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate font-mono text-sm font-medium">{repository.name}</p>
                        <Badge variant="secondary">{repository.category}</Badge>
                        <Badge variant={repository.is_active ? "default" : "secondary"}>
                          {repository.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </div>
                      <p className="truncate text-xs text-muted-foreground">{repository.url}</p>
                      <p className="text-xs text-muted-foreground">
                        branch: {repository.branch} · auth: {repository.auth_type ?? "token"}
                        {repository.credential_name
                          ? ` · credential: ${repository.credential_name}`
                          : ""}
                      </p>
                      {repository.sync_status ? (
                        <p className="text-xs text-muted-foreground">
                          Last sync: {repository.sync_status}
                          {repository.last_sync
                            ? ` · ${new Date(repository.last_sync).toLocaleString()}`
                            : ""}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        aria-label={`Sync ${repository.name}`}
                        size="icon"
                        type="button"
                        variant="ghost"
                        disabled={syncRepository.isPending}
                        onClick={() => syncRepository.mutate(repository.id)}
                        title="Sync (clone if missing, pull if present)"
                      >
                        <RotateCcw className="size-4" />
                      </Button>
                      <Button
                        aria-label={`Edit ${repository.name}`}
                        size="icon"
                        type="button"
                        variant="ghost"
                        onClick={() => setEditing(repository)}
                      >
                        <Pencil className="size-4" />
                      </Button>
                      <Button
                        aria-label={`Delete ${repository.name}`}
                        size="icon"
                        type="button"
                        variant="ghost"
                        onClick={() => setDeleteTarget(repository)}
                      >
                        <Trash2 className="size-4 text-destructive" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <GitRepositoryDialog
        open={editing !== undefined}
        repository={editing ?? null}
        onClose={() => setEditing(undefined)}
      />

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove Git repository?</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `Workflow steps referencing "${deleteTarget.name}" will fail until reconfigured. Existing history in the remote repository is not deleted.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteRepository.isPending}
              onClick={() => {
                if (!deleteTarget) return;
                deleteRepository.mutate(deleteTarget.id, {
                  onSuccess: () => setDeleteTarget(null),
                });
              }}
            >
              {deleteRepository.isPending ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={removeAndCloneTarget !== null}
        onOpenChange={(open) => !open && setRemoveAndCloneTarget(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove and re-clone?</DialogTitle>
            <DialogDescription>
              {removeAndCloneTarget
                ? `This will delete the local copy of "${removeAndCloneTarget.name}" and clone it fresh from the remote. Any uncommitted local changes will be lost.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRemoveAndCloneTarget(null)}>
              Cancel
            </Button>
            <Button
              disabled={removeAndSyncRepository.isPending}
              type="button"
              variant="destructive"
              onClick={() => {
                if (!removeAndCloneTarget) return;
                removeAndSyncRepository.mutate(removeAndCloneTarget.id, {
                  onSuccess: () => setRemoveAndCloneTarget(null),
                });
              }}
            >
              {removeAndSyncRepository.isPending ? "Cloning…" : "Remove and Clone"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
