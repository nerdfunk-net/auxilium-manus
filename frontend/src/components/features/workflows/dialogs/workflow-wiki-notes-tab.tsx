"use client";

import ReactMarkdown from "react-markdown";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import { useWorkflowNotesMutation } from "@/hooks/queries/use-workflow-notes-mutation";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

// Tailwind's preflight strips default heading/list spacing, so a plain
// ReactMarkdown render looks flat — these arbitrary-variant utilities restore
// just enough structure (heading weight/size, list bullets, code background)
// without pulling in the @tailwindcss/typography plugin.
const MARKDOWN_PREVIEW_CLASSES =
  "text-sm leading-relaxed " +
  "[&_h1]:mt-3 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:first:mt-0 " +
  "[&_h2]:mt-3 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:first:mt-0 " +
  "[&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold " +
  "[&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 " +
  "[&_li]:mb-0.5 [&_a]:text-primary [&_a]:underline " +
  "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs " +
  "[&_pre]:mb-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted [&_pre]:p-2 " +
  "[&_blockquote]:mb-2 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground";

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
      <Tabs defaultValue="write" className="flex min-h-0 flex-1 flex-col gap-2">
        <TabsList className="w-fit">
          <TabsTrigger value="write">Write</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
        </TabsList>
        <TabsContent value="write" className="min-h-0 flex-1">
          <Textarea
            className="h-full min-h-[280px] resize-none font-mono text-sm"
            onChange={(e) => onDraftChange(e.target.value)}
            placeholder="Describe what this workflow does, when to run it, and anything else worth knowing…"
            value={draft}
          />
        </TabsContent>
        <TabsContent
          value="preview"
          className="min-h-0 flex-1 overflow-y-auto rounded-md border p-3"
        >
          {draft.trim() ? (
            <div className={MARKDOWN_PREVIEW_CLASSES}>
              <ReactMarkdown>{draft}</ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing to preview yet.</p>
          )}
        </TabsContent>
      </Tabs>
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
