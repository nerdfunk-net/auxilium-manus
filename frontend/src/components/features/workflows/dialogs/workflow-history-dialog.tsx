"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { History, RotateCcw } from "lucide-react";

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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowGitDiffMutation } from "@/hooks/queries/use-workflow-git-diff-mutation";
import { useWorkflowGitHistoryQuery } from "@/hooks/queries/use-workflow-git-history-query";
import { useWorkflowGitRestoreMutation } from "@/hooks/queries/use-workflow-git-restore-mutation";
import { cn } from "@/lib/utils";

import type { WorkflowGitCommitEntry, WorkflowResponse } from "../types/workflow-persistence";
import { WorkflowGitDiffViewer } from "../components/workflow-git-diff-viewer";

interface WorkflowHistoryDialogProps {
  open: boolean;
  workflowId: number | null;
  workflowName: string;
  onClose: () => void;
  onRestored: (updated: WorkflowResponse) => void;
}

function reconstructContent(lines: { content: string }[]): string {
  return lines.map((line) => line.content).join("\n");
}

export function WorkflowHistoryDialog({
  open,
  workflowId,
  workflowName,
  onClose,
  onRestored,
}: WorkflowHistoryDialogProps) {
  const { toast } = useToast();
  const { data, isLoading, error } = useWorkflowGitHistoryQuery({
    workflowId,
    enabled: open,
  });
  const diffMutation = useWorkflowGitDiffMutation(workflowId);
  const restoreMutation = useWorkflowGitRestoreMutation(workflowId);

  const commits = useMemo(() => data?.commits ?? [], [data]);
  const [selectedHash, setSelectedHash] = useState<string | null>(null);

  const { reset: resetDiff } = diffMutation;

  // Unmount Monaco's DiffEditor (by clearing the selection, in its own
  // commit) before the Dialog's portal unmounts in a later commit — doing
  // both in the same tick races Monaco's internal diff-worker teardown
  // against Radix ripping the whole subtree out of the DOM, which throws
  // "TextModel got disposed before DiffEditorWidget model got reset".
  const closeAfterUnmountingDiff = useCallback(() => {
    setSelectedHash(null);
    resetDiff();
    setTimeout(onClose, 0);
  }, [onClose, resetDiff]);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        closeAfterUnmountingDiff();
      }
    },
    [closeAfterUnmountingDiff],
  );

  const selectedIndex = commits.findIndex((c) => c.hash === selectedHash);
  const selectedCommit: WorkflowGitCommitEntry | undefined = commits[selectedIndex];
  const parentCommit: WorkflowGitCommitEntry | undefined = commits[selectedIndex + 1];

  useEffect(() => {
    if (!selectedCommit || !parentCommit) return;
    diffMutation.mutate({ commitA: parentCommit.hash, commitB: selectedCommit.hash });
    // Only re-run when the selection itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCommit?.hash, parentCommit?.hash]);

  const handleRestore = () => {
    if (!selectedCommit) return;
    restoreMutation.mutate(selectedCommit.hash, {
      onSuccess: (updated) => {
        toast({
          title: "Restored",
          description: `Workflow restored to ${selectedCommit.short_hash}.`,
        });
        onRestored(updated);
        closeAfterUnmountingDiff();
      },
      onError: (err: Error) => {
        toast({ title: "Restore failed", description: err.message, variant: "destructive" });
      },
    });
  };

  const diff = diffMutation.data;
  const originalContent = diff ? reconstructContent(diff.left_lines) : "";
  const modifiedContent = diff ? reconstructContent(diff.right_lines) : "";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex h-[85vh] max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="flex items-center gap-2">
            <History className="size-4" />
            History — {workflowName}
          </DialogTitle>
          <DialogDescription>
            Every commit is a saved version of this workflow. Select one to see what changed, or
            restore it.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="w-80 shrink-0 overflow-y-auto border-r">
            {isLoading ? (
              <p className="p-4 text-sm text-muted-foreground">Loading history…</p>
            ) : error ? (
              <p className="p-4 text-sm text-destructive">Failed to load history.</p>
            ) : commits.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No commits yet for this workflow.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Commit</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {commits.map((commit, index) => (
                    <TableRow
                      key={commit.hash}
                      className={cn(
                        "cursor-pointer",
                        commit.hash === selectedHash && "bg-primary/5",
                      )}
                      onClick={() => setSelectedHash(commit.hash)}
                    >
                      <TableCell className="py-2">
                        <div className="flex items-center gap-2">
                          <code className="text-xs text-muted-foreground">
                            {commit.short_hash}
                          </code>
                          {index === 0 ? <Badge variant="outline">Latest</Badge> : null}
                        </div>
                        <p className="mt-0.5 truncate text-sm">{commit.message}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {commit.author.name} · {new Date(commit.date).toLocaleString()}
                        </p>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          <div className="flex min-h-0 flex-1 flex-col">
            {!selectedCommit ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                Select a commit to view its diff.
              </div>
            ) : !parentCommit ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                This is the initial version — nothing to compare it to.
              </div>
            ) : diff ? (
              // Stays mounted across later commit switches (TanStack Query
              // keeps the previous mutation result until the next one
              // resolves) — swapping Monaco's DiffEditor in and out on every
              // click destabilizes its internal diff-worker teardown.
              <div className="relative min-h-0 flex-1">
                <WorkflowGitDiffViewer original={originalContent} modified={modifiedContent} />
                {diffMutation.isPending ? (
                  <div className="absolute inset-x-0 top-0 bg-muted/90 px-3 py-1 text-center text-xs text-muted-foreground">
                    Updating…
                  </div>
                ) : null}
              </div>
            ) : diffMutation.isError ? (
              <div className="flex flex-1 items-center justify-center text-sm text-destructive">
                Failed to load diff.
              </div>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                Loading diff…
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="border-t px-6 py-4">
          <Button type="button" variant="outline" onClick={closeAfterUnmountingDiff}>
            Close
          </Button>
          <Button
            type="button"
            disabled={!selectedCommit || restoreMutation.isPending}
            onClick={handleRestore}
          >
            <RotateCcw className="size-4" />
            {restoreMutation.isPending ? "Restoring…" : "Restore this version"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
