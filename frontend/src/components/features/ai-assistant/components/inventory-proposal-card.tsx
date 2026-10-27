"use client";

import { Check, X } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { InventoryProposal } from "../types/ai-assistant";
import { describeConditionTree } from "../utils/describe-condition-tree";

interface InventoryProposalCardProps {
  proposal: InventoryProposal;
  /** Fingerprint of the builder's filter right now, to warn when it changed since the proposal. */
  currentFingerprint: string;
  onApply: () => void;
  onReject: () => void;
}

/** A checked inventory filter. Applying only fills the builder; nothing is saved. */
export function InventoryProposalCard({
  proposal,
  currentFingerprint,
  onApply,
  onReject,
}: InventoryProposalCardProps) {
  const pending = proposal.state === "pending";
  const builderChanged = pending && proposal.baseFingerprint !== currentFingerprint;
  return (
    <div className="space-y-2 rounded-md border bg-card p-3" data-testid="inventory-proposal">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">{proposal.summary || "Proposed inventory"}</p>
        {proposal.totalCount !== null && (
          <Badge variant="outline" className="shrink-0">
            {proposal.totalCount} device{proposal.totalCount === 1 ? "" : "s"}
          </Badge>
        )}
      </div>
      <ul className="space-y-0.5 rounded border bg-muted/30 p-2 font-mono text-xs">
        {describeConditionTree(proposal.tree).map((line, index) => (
          <li key={`${index}-${line}`} className="break-all whitespace-pre-wrap">
            {line}
          </li>
        ))}
      </ul>
      {proposal.warnings.map((warning) => (
        <Alert key={warning}>
          <AlertDescription>{warning}</AlertDescription>
        </Alert>
      ))}
      {builderChanged && (
        <Alert>
          <AlertDescription>
            The filter in the builder changed after this proposal was made. Applying replaces it,
            including those edits.
          </AlertDescription>
        </Alert>
      )}
      {pending ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" size="sm" onClick={onApply}>
            <Check className="size-4" />
            Apply to builder
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={onReject}>
            <X className="size-4" />
            Reject
          </Button>
          <span className="text-xs text-muted-foreground">
            Nothing is saved: review it, then use Save.
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {proposal.state === "applied" ? "Applied to the inventory builder." : "Rejected."}
        </p>
      )}
    </div>
  );
}
