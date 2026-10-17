"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGitRepositoriesQuery } from "@/hooks/queries/use-git-repositories-query";

interface GitRepositorySelectDialogProps {
  open: boolean;
  selectedRepositoryId: number | null;
  onClose: () => void;
  onSave: (repositoryId: number) => void;
  /** Distinct DOM id so two instances on the same page (unlikely, but
   * multiple git-backed steps can appear on one canvas) don't collide. */
  idPrefix?: string;
  description?: string;
}

const DEFAULT_DESCRIPTION =
  "A configured Git repository is required. Choose which repository (from Settings → Git " +
  "Repositories) this step should use.";

export function GitRepositorySelectDialog({
  open,
  selectedRepositoryId,
  onClose,
  onSave,
  idPrefix = "git-repository-select",
  description = DEFAULT_DESCRIPTION,
}: GitRepositorySelectDialogProps) {
  const router = useRouter();
  const [repositoryId, setRepositoryId] = useState<number | null>(selectedRepositoryId);
  const [prevOpen, setPrevOpen] = useState(open);
  const { data, isLoading } = useGitRepositoriesQuery({ activeOnly: true, enabled: open });

  const repositories = data?.repositories ?? [];

  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setRepositoryId(selectedRepositoryId);
    }
  }

  const handleSave = useCallback(() => {
    if (repositoryId === null) {
      return;
    }
    onSave(repositoryId);
    onClose();
  }, [onClose, onSave, repositoryId]);

  const fieldId = `${idPrefix}-select`;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Git repository</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading repositories…</p>
          ) : repositories.length === 0 ? (
            <div className="rounded-lg border border-dashed bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
              <p>No Git repositories configured yet.</p>
              <Button
                className="mt-3 h-8"
                size="sm"
                type="button"
                variant="outline"
                onClick={() => {
                  onClose();
                  router.push("/settings/git-repositories");
                }}
              >
                Open Settings → Git Repositories
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor={fieldId}>Repository</Label>
              <Select
                value={repositoryId !== null ? String(repositoryId) : ""}
                onValueChange={(value) => setRepositoryId(Number(value))}
              >
                <SelectTrigger id={fieldId}>
                  <SelectValue placeholder="Select a Git repository" />
                </SelectTrigger>
                <SelectContent>
                  {repositories.map((repository) => (
                    <SelectItem key={repository.id} value={String(repository.id)}>
                      <span className="font-mono">{repository.name}</span>
                      <span className="ml-2 text-muted-foreground">— {repository.url}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={repositoryId === null || repositories.length === 0}
            type="button"
            onClick={handleSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
