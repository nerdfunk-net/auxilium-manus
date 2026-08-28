"use client";

import { useState } from "react";
import { GitBranch, Pencil, Trash2 } from "lucide-react";

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
import { useGitRepositoriesQuery } from "@/hooks/queries/use-git-repositories-query";

import { WorkflowGitRepositoryDialog } from "../dialogs/workflow-git-repository-dialog";

const WORKFLOW_GIT_CATEGORY = "workflows";

export function VersionControlSettingsCanvas() {
  const { data, isLoading, error } = useGitRepositoriesQuery({
    activeOnly: false,
    category: WORKFLOW_GIT_CATEGORY,
  });
  const { deleteRepository } = useGitRepositoriesMutations();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  const repository = data?.repositories[0] ?? null;

  return (
    <>
      <div className="flex h-full flex-col overflow-y-auto bg-muted p-10">
        <div className="mx-auto w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
          <div className="mb-6 flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <GitBranch className="size-6" />
            </div>
            <div>
              <p className="text-sm font-semibold">Version Control</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Configure a single Git repository for version-controlled workflows. Once
                configured, any workflow can turn version control on in its Manage dialog — every
                save then commits and pushes the workflow definition here automatically.
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-dashed bg-muted/30 p-6">
            {isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : error ? (
              <p className="text-sm text-destructive">
                Failed to load Git repository configuration: {error.message}
              </p>
            ) : repository ? (
              <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium">{repository.url}</p>
                    <Badge variant={repository.is_active ? "default" : "secondary"}>
                      {repository.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    branch: {repository.branch} · auth: {repository.auth_type ?? "token"}
                    {repository.credential_name ? ` · credential: ${repository.credential_name}` : ""}
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
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setIsDialogOpen(true)}
                  >
                    <Pencil className="size-4" />
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setIsDeleteOpen(true)}
                  >
                    <Trash2 className="size-4" />
                    Remove
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <p className="text-sm text-muted-foreground">
                  No Git repository configured yet. Workflows can&apos;t be version controlled
                  until one is set up.
                </p>
                <Button type="button" onClick={() => setIsDialogOpen(true)}>
                  Configure repository
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>

      <WorkflowGitRepositoryDialog
        open={isDialogOpen}
        repository={repository}
        onClose={() => setIsDialogOpen(false)}
      />

      <Dialog open={isDeleteOpen} onOpenChange={(open) => !open && setIsDeleteOpen(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove Git repository?</DialogTitle>
            <DialogDescription>
              Workflows currently set to version controlled will keep that flag but stop syncing
              until a repository is configured again. Existing history in the remote repository is
              not deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setIsDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleteRepository.isPending}
              onClick={() => {
                if (!repository) return;
                deleteRepository.mutate(repository.id, {
                  onSuccess: () => setIsDeleteOpen(false),
                });
              }}
            >
              {deleteRepository.isPending ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
