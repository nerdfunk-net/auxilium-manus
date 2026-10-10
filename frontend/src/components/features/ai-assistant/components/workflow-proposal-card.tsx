"use client";

import { Check, Minus, Pencil, Plus, X } from "lucide-react";
import { useMemo } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type {
  WorkflowChangeEdge,
  WorkflowChangedNode,
  WorkflowProposal,
} from "../types/ai-assistant";
import { buildLineDiff } from "../utils/line-diff";

interface WorkflowProposalCardProps {
  proposal: WorkflowProposal;
  /** Fingerprint of the canvas right now, to warn when it changed since the proposal. */
  currentFingerprint: string;
  onApply: () => void;
  onReject: () => void;
}

const edgeText = (edge: WorkflowChangeEdge) =>
  `${edge.from} —${edge.outcome}→ ${edge.to}`;

function ChangedStep({ step }: { step: WorkflowChangedNode }) {
  const diff = useMemo(
    () => buildLineDiff(step.before, step.after),
    [step.before, step.after],
  );
  return (
    <li className="space-y-1">
      <div className="flex items-center gap-1 text-sm">
        <Pencil className="size-3 shrink-0" aria-hidden />
        <span className="font-medium">{step.title}</span>
        <span className="text-xs text-muted-foreground">
          ({step.kind}) — {step.fields.join(", ")}
        </span>
      </div>
      <pre className="max-h-40 overflow-auto rounded border bg-muted/30 font-mono text-xs">
        {diff.rows.map((row, index) => (
          <div
            key={index}
            className={`flex px-2 ${row.kind === "added" ? "bg-primary/10" : row.kind === "removed" ? "bg-destructive/10" : ""}`}
          >
            <span className="w-4 shrink-0 select-none" aria-hidden>
              {row.kind === "added" ? "+" : row.kind === "removed" ? "-" : " "}
            </span>
            <span className="whitespace-pre-wrap break-all">
              {row.kind === "gap"
                ? `… ${row.hidden} unchanged lines …`
                : row.text}
            </span>
          </div>
        ))}
      </pre>
    </li>
  );
}

export function WorkflowProposalCard({
  proposal,
  currentFingerprint,
  onApply,
  onReject,
}: WorkflowProposalCardProps) {
  const { changes } = proposal;
  const pending = proposal.state === "pending";
  const canvasChanged =
    pending && proposal.baseFingerprint !== currentFingerprint;
  const total =
    changes.nodes_added.length +
    changes.nodes_removed.length +
    changes.nodes_changed.length +
    changes.edges_added.length +
    changes.edges_removed.length;

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="workflow-proposal"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">
          {proposal.summary || "Proposed workflow change"}
        </p>
        <Badge variant="outline" className="shrink-0">
          {total} change{total === 1 ? "" : "s"}
        </Badge>
      </div>

      {proposal.warnings.map((warning) => (
        <Alert key={`${warning.node_id}-${warning.code}-${warning.message}`}>
          <AlertDescription>
            {warning.node_id ? `${warning.node_id}: ` : ""}
            {warning.message}
          </AlertDescription>
        </Alert>
      ))}
      {canvasChanged && (
        <Alert>
          <AlertDescription>
            The canvas changed after this proposal was made. Applying replaces
            the current steps and connections with the proposed ones, including
            those edits.
          </AlertDescription>
        </Alert>
      )}

      <ul className="space-y-2">
        {changes.nodes_added.map((step) => (
          <li key={`add-${step.id}`} className="space-y-1">
            <div className="flex items-center gap-1 text-sm">
              <Plus className="size-3 shrink-0 text-primary" aria-hidden />
              <span className="font-medium">{step.title}</span>
              <span className="text-xs text-muted-foreground">
                ({step.kind}) added
              </span>
            </div>
            {step.config && step.config !== "{}" && (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">
                  Configuration
                </summary>
                <pre className="max-h-40 overflow-auto rounded border bg-muted/30 p-2 font-mono whitespace-pre-wrap break-all">
                  {step.config}
                </pre>
              </details>
            )}
          </li>
        ))}
        {changes.nodes_removed.map((step) => (
          <li key={`rm-${step.id}`} className="flex items-center gap-1 text-sm">
            <Minus className="size-3 shrink-0 text-destructive" aria-hidden />
            <span className="font-medium">{step.title}</span>
            <span className="text-xs text-muted-foreground">
              ({step.kind}) removed
            </span>
          </li>
        ))}
        {changes.nodes_changed.map((step) => (
          <ChangedStep key={`chg-${step.id}`} step={step} />
        ))}
        {changes.edges_added.map((edge) => (
          <li
            key={`ea-${edgeText(edge)}`}
            className="flex items-center gap-1 text-xs"
          >
            <Plus className="size-3 shrink-0 text-primary" aria-hidden />
            <code>{edgeText(edge)}</code>
          </li>
        ))}
        {changes.edges_removed.map((edge) => (
          <li
            key={`er-${edgeText(edge)}`}
            className="flex items-center gap-1 text-xs"
          >
            <Minus className="size-3 shrink-0 text-destructive" aria-hidden />
            <code>{edgeText(edge)}</code>
          </li>
        ))}
        {changes.static_attributes_changed && (
          <li className="flex items-center gap-1 text-sm">
            <Pencil className="size-3 shrink-0" aria-hidden />
            Run inputs (static attributes) changed
          </li>
        )}
      </ul>

      {pending ? (
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" onClick={onApply}>
            <Check className="size-4" />
            Apply to canvas
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
            ? "Applied to the canvas. Review it, then save the workflow."
            : "Rejected."}
        </p>
      )}
    </div>
  );
}
