"use client";

import { useCallback, useMemo } from "react";

import type { WorkflowNotesTarget } from "@/components/features/ai-assistant/components/assistant-panel";
import type { WorkflowNotesProposal } from "@/components/features/ai-assistant/types/ai-assistant";
import { useWorkflowNotesMutation } from "@/hooks/queries/use-workflow-notes-mutation";
import { useToast } from "@/hooks/use-toast";

import { useWorkflowBuilderStore } from "./use-workflow-builder-store";

/**
 * Where the assistant's wiki-notes proposals are saved. The user's click on the proposal card
 * calls this; it saves through the ordinary notes endpoint (the user's own permissions) and
 * refreshes the builder store, so the Wiki dialog shows the new notes.
 */
export function useAssistantNotesTarget(
  workflowId: number | null,
): WorkflowNotesTarget {
  const { toast } = useToast();
  const savedNotes = useWorkflowBuilderStore((state) => state.workflowNotes);
  const setWorkflowNotes = useWorkflowBuilderStore(
    (state) => state.setWorkflowNotes,
  );
  const { mutateAsync: saveNotes } = useWorkflowNotesMutation(workflowId);

  const onApply = useCallback(
    async (proposal: WorkflowNotesProposal): Promise<boolean> => {
      if (workflowId == null || proposal.workflowId !== workflowId) {
        toast({
          title: "Failed to save notes",
          description: "This proposal is for another workflow.",
          variant: "destructive",
        });
        return false;
      }
      try {
        const response = await saveNotes(proposal.notes);
        setWorkflowNotes(response.notes);
        toast({ title: "Notes saved", description: "The wiki was updated." });
        return true;
      } catch (error) {
        toast({
          title: "Failed to save notes",
          description:
            error instanceof Error ? error.message : "Unexpected error",
          variant: "destructive",
        });
        return false;
      }
    },
    [workflowId, saveNotes, setWorkflowNotes, toast],
  );

  return useMemo(
    () => ({ currentNotes: savedNotes ?? "", onApply }),
    [savedNotes, onApply],
  );
}
