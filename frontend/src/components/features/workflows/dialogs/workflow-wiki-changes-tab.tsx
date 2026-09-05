"use client";

import { useCallback, useState } from "react";
import { GitCompareArrows } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useWorkflowChangesQuery } from "@/hooks/queries/use-workflow-changes-query";
import { useWorkflowGitDiffMutation } from "@/hooks/queries/use-workflow-git-diff-mutation";

import type { WorkflowChangeEntry } from "../types/workflow-persistence";
import { WorkflowGitDiffViewer } from "../components/workflow-git-diff-viewer";

interface WorkflowWikiChangesTabProps {
  workflowId: number | null;
  open: boolean;
}

function reconstructContent(lines: { content: string }[]): string {
  return lines.map((line) => line.content).join("\n");
}

function actionLabel(action: WorkflowChangeEntry["action"]): string {
  return action === "created" ? "Created" : "Updated";
}

export function WorkflowWikiChangesTab({ workflowId, open }: WorkflowWikiChangesTabProps) {
  const { data, isLoading, error } = useWorkflowChangesQuery({ workflowId, enabled: open });
  const diffMutation = useWorkflowGitDiffMutation(workflowId);
  const [selectedChange, setSelectedChange] = useState<WorkflowChangeEntry | null>(null);

  const { mutate: loadDiff, reset: resetDiff } = diffMutation;

  const handleViewDiff = useCallback(
    (change: WorkflowChangeEntry) => {
      if (!change.commit_sha || !change.parent_commit_sha) return;
      setSelectedChange(change);
      loadDiff({ commitA: change.parent_commit_sha, commitB: change.commit_sha });
    },
    [loadDiff],
  );

  // See WorkflowHistoryDialog: clear the selection (unmounting Monaco's
  // DiffEditor) before the Dialog's own portal unmounts in a later commit.
  const closeDiff = useCallback(() => {
    setSelectedChange(null);
    resetDiff();
  }, [resetDiff]);

  const changes = data?.changes ?? [];
  const diff = diffMutation.data;
  const originalContent = diff ? reconstructContent(diff.left_lines) : "";
  const modifiedContent = diff ? reconstructContent(diff.right_lines) : "";

  if (workflowId == null) {
    return (
      <p className="text-sm text-muted-foreground">
        Save this workflow to start recording changes.
      </p>
    );
  }

  return (
    <>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading changes…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Failed to load changes.</p>
      ) : changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No changes recorded yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>When</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {changes.map((change) => (
              <TableRow key={change.id}>
                <TableCell className="text-sm">{change.actor_username ?? "Unknown"}</TableCell>
                <TableCell className="text-sm">{actionLabel(change.action)}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(change.created_at).toLocaleString()}
                </TableCell>
                <TableCell>
                  {change.has_diff ? (
                    <button
                      aria-label="View diff"
                      className="flex items-center justify-center rounded-[7px] p-1.5 text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => handleViewDiff(change)}
                      title="View diff"
                      type="button"
                    >
                      <GitCompareArrows className="size-3.5" aria-hidden />
                    </button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <Dialog open={selectedChange !== null} onOpenChange={(next) => !next && closeDiff()}>
        <DialogContent className="flex h-[70vh] max-h-[70vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
          <DialogHeader className="border-b px-6 py-4">
            <DialogTitle>Diff</DialogTitle>
          </DialogHeader>
          <div className="relative min-h-0 flex-1">
            {diff ? (
              <WorkflowGitDiffViewer original={originalContent} modified={modifiedContent} />
            ) : diffMutation.isError ? (
              <div className="flex h-full items-center justify-center text-sm text-destructive">
                Failed to load diff.
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading diff…
              </div>
            )}
          </div>
          <DialogFooter className="border-t px-6 py-4">
            <Button onClick={closeDiff} type="button" variant="outline">
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
