"use client";

import { Check, Loader2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { WorkflowNotesProposal } from "../types/ai-assistant";
import { buildLineDiff } from "../utils/line-diff";

interface WorkflowNotesProposalCardProps {
  proposal: WorkflowNotesProposal;
  /** The saved notes right now, so the diff and the drift warning use what the wiki holds. */
  currentNotes: string;
  /** Saves the notes; resolves true when they were saved (the card then reports "applied"). */
  onApply: () => Promise<boolean>;
  onReject: () => void;
}

/** Notes often lack a final newline; without this the last line would show as changed. */
const withFinalNewline = (text: string): string =>
  text === "" || text.endsWith("\n") ? text : `${text}\n`;

const ROW_STYLES = {
  added: "bg-primary/10",
  removed: "bg-destructive/10",
  context: "",
  gap: "text-muted-foreground italic",
} as const;

const ROW_MARKERS = {
  added: "+",
  removed: "-",
  context: " ",
  gap: " ",
} as const;

export function WorkflowNotesProposalCard({
  proposal,
  currentNotes,
  onApply,
  onReject,
}: WorkflowNotesProposalCardProps) {
  const [saving, setSaving] = useState(false);
  const diff = useMemo(
    () =>
      buildLineDiff(
        withFinalNewline(currentNotes),
        withFinalNewline(proposal.notes),
      ),
    [currentNotes, proposal.notes],
  );
  const pending = proposal.state === "pending";
  const notesChanged = pending && proposal.baseNotes !== currentNotes;

  const handleApply = async () => {
    setSaving(true);
    try {
      await onApply();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="workflow-notes-proposal"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">
          {proposal.summary || "Proposed wiki notes"}
        </p>
        <div className="flex shrink-0 items-center gap-1 text-xs">
          <Badge variant="outline">+{diff.added}</Badge>
          <Badge variant="outline">-{diff.removed}</Badge>
        </div>
      </div>

      {proposal.warnings.map((warning) => (
        <Alert key={warning}>
          <AlertDescription>{warning}</AlertDescription>
        </Alert>
      ))}
      {notesChanged && (
        <Alert>
          <AlertDescription>
            The saved notes changed after this proposal was made. Applying
            replaces them completely.
          </AlertDescription>
        </Alert>
      )}

      <pre
        className="max-h-72 overflow-auto rounded border bg-muted/30 font-mono text-xs"
        aria-label="Proposed notes changes"
      >
        {diff.rows.map((row, index) => (
          <div key={index} className={`flex px-2 ${ROW_STYLES[row.kind]}`}>
            <span className="w-4 shrink-0 select-none" aria-hidden>
              {ROW_MARKERS[row.kind]}
            </span>
            <span className="whitespace-pre-wrap break-all">
              {row.kind === "gap"
                ? `… ${row.hidden} unchanged lines …`
                : row.text}
            </span>
          </div>
        ))}
      </pre>

      {pending ? (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={saving}
            onClick={() => void handleApply()}
          >
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            Save notes
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={saving}
            onClick={onReject}
          >
            <X className="size-4" />
            Reject
          </Button>
          <span className="text-xs text-muted-foreground">
            Saved to the wiki only when you click Save notes.
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {proposal.state === "applied" ? "Notes saved." : "Rejected."}
        </p>
      )}
    </div>
  );
}
