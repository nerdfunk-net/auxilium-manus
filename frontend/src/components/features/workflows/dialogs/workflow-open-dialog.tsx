"use client";

import { FileText } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";
import { cn } from "@/lib/utils";

import { WorkflowFolderSidebar } from "../components/workflow-folder-sidebar";
import type { WorkflowSummary } from "../types/workflow-persistence";
import {
  buildFolderCounts,
  getFolderLabel,
  getSortedFolders,
  normalizeFolder,
} from "../utils/workflow-folders";

interface WorkflowOpenDialogProps {
  open: boolean;
  onOpen: (workflow: WorkflowSummary) => void;
  onClose: () => void;
}

export function WorkflowOpenDialog({
  open,
  onOpen,
  onClose,
}: WorkflowOpenDialogProps) {
  const { data, isLoading, error } = useWorkflowsQuery();
  const workflows = useMemo(() => data?.workflows ?? [], [data]);

  const folderCounts = useMemo(() => buildFolderCounts(workflows), [workflows]);
  const sortedFolders = useMemo(() => getSortedFolders(folderCounts), [folderCounts]);

  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);

  const filteredWorkflows = useMemo(
    () =>
      selectedFolder === null
        ? workflows
        : workflows.filter((wf) => normalizeFolder(wf.folder) === selectedFolder),
    [workflows, selectedFolder],
  );

  const handleSelect = useCallback(
    (workflow: WorkflowSummary) => {
      onOpen(workflow);
      onClose();
    },
    [onOpen, onClose],
  );

  const selectedFolderLabel =
    selectedFolder === null ? "ALL" : getFolderLabel(selectedFolder).toUpperCase();

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>Open Workflow</DialogTitle>
          <DialogDescription>Browse and open a saved workflow.</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <WorkflowFolderSidebar
            totalCount={workflows.length}
            folderCounts={folderCounts}
            sortedFolders={sortedFolders}
            selectedFolder={selectedFolder}
            onSelectFolder={setSelectedFolder}
          />

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto p-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Workflows in{" "}
                <span className="text-primary">{selectedFolderLabel}</span>
              </p>

              {isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : error ? (
                <p className="text-sm text-destructive">Failed to load workflows.</p>
              ) : filteredWorkflows.length === 0 ? (
                <p className="text-sm italic text-muted-foreground">
                  No workflows in this folder.
                </p>
              ) : (
                <div className="space-y-2">
                  {filteredWorkflows.map((wf) => (
                    <WorkflowSelectRow
                      key={wf.id}
                      workflow={wf}
                      onSelect={handleSelect}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end border-t px-6 py-4">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface WorkflowSelectRowProps {
  workflow: WorkflowSummary;
  onSelect: (workflow: WorkflowSummary) => void;
}

function WorkflowSelectRow({ workflow, onSelect }: WorkflowSelectRowProps) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center rounded-lg border p-4 text-left transition-colors",
        "hover:border-primary/30 hover:bg-primary/5",
      )}
      onClick={() => onSelect(workflow)}
    >
      <FileText className="mr-3 size-5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{workflow.name}</span>
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {getFolderLabel(workflow.folder)}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {workflow.creator_username ?? "—"} ·{" "}
          {new Date(workflow.updated_at).toLocaleDateString()}
        </p>
      </div>
    </button>
  );
}
