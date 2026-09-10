"use client";

import { Button } from "@/components/ui/button";
import { MarkdownEditor } from "@/components/ui/markdown-editor";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowNotesMutation } from "@/hooks/queries/use-workflow-notes-mutation";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

interface WorkflowWikiNotesTabProps {
  workflowId: number | null;
  /** Owned by WorkflowWikiDialog so it survives a Notes/Changes tab switch
   * (Radix unmounts the inactive TabsContent, which would otherwise wipe
   * local state here). */
  draft: string;
  onDraftChange: (draft: string) => void;
  onClose: () => void;
}

export function WorkflowWikiNotesTab({
  workflowId,
  draft,
  onDraftChange,
  onClose,
}: WorkflowWikiNotesTabProps) {
  const workflowNotes = useWorkflowBuilderStore((state) => state.workflowNotes);
  const setWorkflowNotes = useWorkflowBuilderStore((state) => state.setWorkflowNotes);
  const { toast } = useToast();
  const notesMutation = useWorkflowNotesMutation(workflowId);

  if (workflowId == null) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Save this workflow before adding notes.
        </p>
        <div className="flex items-center justify-end gap-2">
          <Button onClick={onClose} size="sm" variant="outline">
            Close
          </Button>
        </div>
      </div>
    );
  }

  const isDirty = draft !== (workflowNotes ?? "");

  const handleSave = () => {
    notesMutation.mutate(draft, {
      onSuccess: (response) => {
        setWorkflowNotes(response.notes);
        toast({ title: "Notes saved", description: "Your changes have been saved." });
      },
      onError: (err: Error) => {
        toast({
          title: "Failed to save notes",
          description: err.message,
          variant: "destructive",
        });
      },
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <MarkdownEditor
        value={draft}
        onChange={onDraftChange}
        placeholder="Describe what this workflow does, when to run it, and anything else worth knowing…"
      />
      <div className="flex items-center justify-end gap-2">
        <Button onClick={onClose} size="sm" variant="outline">
          Close
        </Button>
        <Button disabled={!isDirty || notesMutation.isPending} onClick={handleSave} size="sm">
          {notesMutation.isPending ? "Saving…" : "Save notes"}
        </Button>
      </div>
    </div>
  );
}
