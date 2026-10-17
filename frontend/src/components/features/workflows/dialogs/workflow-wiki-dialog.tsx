"use client";

import { useState } from "react";
import { BookOpen } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { WorkflowWikiChangesTab } from "./workflow-wiki-changes-tab";
import { WorkflowWikiNotesTab } from "./workflow-wiki-notes-tab";

interface WorkflowWikiDialogProps {
  open: boolean;
  workflowId: number | null;
  workflowName: string;
  onClose: () => void;
}

export function WorkflowWikiDialog({
  open,
  workflowId,
  workflowName,
  onClose,
}: WorkflowWikiDialogProps) {
  const workflowNotes = useWorkflowBuilderStore((state) => state.workflowNotes);

  // Owned here (not inside WorkflowWikiNotesTab) because Radix unmounts a
  // TabsContent pane when it's not the active tab — an in-progress note
  // would be wiped the moment the user switched to the Changes tab and back
  // if the draft lived in the Notes tab component itself. This dialog stays
  // mounted across that switch, so the draft survives it.
  const [notesDraft, setNotesDraft] = useState(workflowNotes ?? "");

  // Resync the draft from the store each time the dialog (re)opens, without
  // an effect — see react.dev "Resetting state when a prop changes". Doing
  // this in an effect would setState after the open-triggered render already
  // committed, causing an extra cascading render.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setNotesDraft(workflowNotes ?? "");
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex h-[75vh] max-h-[75vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="flex items-center gap-2">
            <BookOpen className="size-4" />
            Wiki — {workflowName}
          </DialogTitle>
          <DialogDescription>
            Notes describing this workflow, and a log of every save.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="notes" className="flex min-h-0 flex-1 flex-col gap-0">
          <TabsList className="mx-6 mt-4 w-fit">
            <TabsTrigger value="notes">Notes</TabsTrigger>
            <TabsTrigger value="changes">Changes</TabsTrigger>
          </TabsList>
          <TabsContent value="notes" className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-4">
            <WorkflowWikiNotesTab
              draft={notesDraft}
              onClose={onClose}
              onDraftChange={setNotesDraft}
              workflowId={workflowId}
            />
          </TabsContent>
          <TabsContent value="changes" className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            <WorkflowWikiChangesTab workflowId={workflowId} open={open} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
