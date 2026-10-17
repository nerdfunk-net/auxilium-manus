"use client";

import { Check, X } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { QueryProposal } from "../types/ai-assistant";
import { describeQuery } from "../utils/describe-query";

interface QueryProposalCardProps {
  proposal: QueryProposal;
  onApply: () => void;
  onReject: () => void;
}

/** A checked report query. Applying only fills the query builder; nothing runs or is saved. */
export function QueryProposalCard({ proposal, onApply, onReject }: QueryProposalCardProps) {
  const pending = proposal.state === "pending";
  return (
    <div className="space-y-2 rounded-md border bg-card p-3" data-testid="query-proposal">
      <p className="text-sm font-medium">{proposal.summary || "Proposed query"}</p>
      <ul className="space-y-0.5 rounded border bg-muted/30 p-2 font-mono text-xs">
        {describeQuery(proposal.query).map((line) => (
          <li key={line} className="break-all">
            {line}
          </li>
        ))}
      </ul>
      {pending ? (
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" onClick={onApply}>
            <Check className="size-4" />
            Apply to Explore
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={onReject}>
            <X className="size-4" />
            Reject
          </Button>
          <span className="text-xs text-muted-foreground">You still run it yourself.</span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {proposal.state === "applied"
            ? "Applied to the query builder on the Explore tab."
            : "Rejected."}
        </p>
      )}
    </div>
  );
}
