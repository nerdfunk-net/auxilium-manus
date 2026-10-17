"use client";

import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { ReportOutlineProposal, SectionTextProposal } from "../types/ai-assistant";
import { describeQuery } from "../utils/describe-query";

interface CardActions {
  onApply: () => void;
  onReject: () => void;
}

function Decision({
  pending,
  state,
  applyLabel,
  appliedText,
  actions,
}: {
  pending: boolean;
  state: string;
  applyLabel: string;
  appliedText: string;
  actions: CardActions;
}) {
  if (!pending) {
    return (
      <p className="text-xs text-muted-foreground">
        {state === "applied" ? appliedText : "Rejected."}
      </p>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <Button type="button" size="sm" onClick={actions.onApply}>
        <Check className="size-4" />
        {applyLabel}
      </Button>
      <Button type="button" size="sm" variant="outline" onClick={actions.onReject}>
        <X className="size-4" />
        Reject
      </Button>
      <span className="text-xs text-muted-foreground">You review and save it yourself.</span>
    </div>
  );
}

/** A drafted report: its sections and their queries in words. Applying opens the report editor. */
export function ReportOutlineCard({
  proposal,
  onApply,
  onReject,
}: { proposal: ReportOutlineProposal } & CardActions) {
  return (
    <div className="space-y-2 rounded-md border bg-card p-3" data-testid="report-outline-proposal">
      <p className="text-sm font-medium">{proposal.summary || `Proposed report: ${proposal.name}`}</p>
      <p className="text-xs text-muted-foreground">Report name: {proposal.name}</p>
      <ol className="space-y-1.5 text-xs">
        {proposal.sections.map((section) => (
          <li key={section.id} className="rounded border bg-muted/30 p-2">
            <p className="font-medium">
              {section.title} <span className="font-normal text-muted-foreground">({section.presentation})</span>
            </p>
            <ul className="font-mono">
              {describeQuery(section.query).map((line) => (
                <li key={line} className="break-all">
                  {line}
                </li>
              ))}
            </ul>
            {section.text ? <p className="mt-1 text-muted-foreground">{section.text}</p> : null}
          </li>
        ))}
      </ol>
      <Decision
        pending={proposal.state === "pending"}
        state={proposal.state}
        applyLabel="Open in report editor"
        appliedText="Opened in the report editor on the Reports tab."
        actions={{ onApply, onReject }}
      />
    </div>
  );
}

/** New text for one section of a saved report. Applying opens that report's editor with it filled in. */
export function SectionTextCard({
  proposal,
  onApply,
  onReject,
}: { proposal: SectionTextProposal } & CardActions) {
  return (
    <div className="space-y-2 rounded-md border bg-card p-3" data-testid="section-text-proposal">
      <p className="text-sm font-medium">{proposal.summary || "Proposed section text"}</p>
      <p className="text-xs text-muted-foreground">Section: {proposal.sectionTitle}</p>
      <p className="whitespace-pre-wrap rounded border bg-muted/30 p-2 text-xs">{proposal.text}</p>
      <Decision
        pending={proposal.state === "pending"}
        state={proposal.state}
        applyLabel="Open in report editor"
        appliedText="Opened in the report editor on the Reports tab."
        actions={{ onApply, onReject }}
      />
    </div>
  );
}
