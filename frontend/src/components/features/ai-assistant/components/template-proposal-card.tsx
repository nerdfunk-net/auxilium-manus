"use client";

import { Check, X } from "lucide-react";
import { useMemo } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { TemplateProposal } from "../types/ai-assistant";
import { buildLineDiff } from "../utils/line-diff";

interface TemplateProposalCardProps {
  proposal: TemplateProposal;
  /** The editor's content right now, so the diff is always against what the user sees. */
  currentContent: string;
  onApply: () => void;
  onReject: () => void;
}

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

export function TemplateProposalCard({
  proposal,
  currentContent,
  onApply,
  onReject,
}: TemplateProposalCardProps) {
  const diff = useMemo(
    () => buildLineDiff(currentContent, proposal.content),
    [currentContent, proposal.content],
  );
  const pending = proposal.state === "pending";
  const bufferChanged = pending && proposal.baseContent !== currentContent;

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="template-proposal"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">
          {proposal.summary || "Proposed change"}
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
      {bufferChanged && (
        <Alert>
          <AlertDescription>
            The editor changed after this proposal was made. Applying replaces
            the whole template, including those edits.
          </AlertDescription>
        </Alert>
      )}

      <pre
        className="max-h-72 overflow-auto rounded border bg-muted/30 font-mono text-xs"
        aria-label="Proposed changes"
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
          <Button type="button" size="sm" onClick={onApply}>
            <Check className="size-4" />
            Apply to editor
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={onReject}>
            <X className="size-4" />
            Reject
          </Button>
          <span className="text-xs text-muted-foreground">
            Not saved until you save.
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {proposal.state === "applied"
            ? "Applied to the editor. Review it, then save the template."
            : "Rejected."}
        </p>
      )}
    </div>
  );
}
