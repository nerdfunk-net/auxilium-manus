"use client";

import { useState } from "react";
import { GitBranch, Plus } from "lucide-react";

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
import { GitRepositoriesTable } from "../git-repositories/components/git-repositories-table";

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
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <GitBranch className="size-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold">Git Repositories</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Repositories used by git-clone / git-pull / git-push / get-git-devices and other
                workflow steps, plus (if one is marked &quot;Workflow version control&quot;) the
                workflow Manage dialog. Each repository supports token or SSH-key auth via
                Settings → Credentials.
              </p>
            </div>
          </div>
          <Button type="button" onClick={() => setEditing(null)}>
            <Plus className="size-4" />
            Add repository
          </Button>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="text-sm text-destructive">
            Failed to load Git repositories: {error.message}
          </p>
        ) : (
          <GitRepositoriesTable
            repositories={repositories}
            isSyncing={syncRepository.isPending}
            isRemovingAndCloning={removeAndSyncRepository.isPending}
            onSync={(repository) => syncRepository.mutate(repository.id)}
            onRemoveAndClone={(repository) => setRemoveAndCloneTarget(repository)}
            onEdit={(repository) => setEditing(repository)}
            onDelete={(repository) => setDeleteTarget(repository)}
          />
        )}
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
    </div>
  );
}
