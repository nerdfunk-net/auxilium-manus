"use client";

import { Loader2, Play, X } from "lucide-react";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { useWorkflowRunConfirmMutation } from "../hooks/use-workflow-run-confirm";
import type {
  WorkflowRunProposal,
  WorkflowRunResult,
} from "../types/ai-assistant";

interface WorkflowRunProposalCardProps {
  proposal: WorkflowRunProposal;
  onResult: (result: WorkflowRunResult) => void;
  onReject: () => void;
  /** Asks the assistant to read the finished run's result (the run id goes into the message). */
  onAskResult?: (result: WorkflowRunResult, workflowName: string) => void;
  /** The assistant is still answering: Run waits, so the answer to the run can follow it. */
  busy?: boolean;
}

const GENERIC_ERROR = "The workflow could not be started";

function isExpired(expiresAt: number): boolean {
  return Date.now() / 1000 >= expiresAt;
}

/**
 * A released workflow the assistant wants run. Workflow, inputs and devices are shown as plain
 * text (never interpreted as markup); the server starts what its signed token says, as the
 * signed-in user. Nothing starts until Run is clicked.
 */
export function WorkflowRunProposalCard({
  proposal,
  onResult,
  onReject,
  onAskResult,
  busy = false,
}: WorkflowRunProposalCardProps) {
  const { mutateAsync, isPending } = useWorkflowRunConfirmMutation();
  const [error, setError] = useState<string | null>(null);

  const pending = proposal.state === "pending";
  const expired = pending && isExpired(proposal.expiresAt);
  const inputs = Object.entries(proposal.inputs);

  const handleRun = async () => {
    if (isExpired(proposal.expiresAt)) {
      setError("This proposal expired. Ask the assistant again.");
      return;
    }
    setError(null);
    try {
      onResult(await mutateAsync(proposal.token));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : GENERIC_ERROR);
    }
  };

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="workflow-run-proposal"
    >
      <p className="text-sm font-medium">
        Run workflow{" "}
        <span className="font-semibold">{proposal.workflow.name}</span>
      </p>

      {inputs.length > 0 && (
        <dl
          className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded border bg-muted/30 p-2 font-mono text-xs"
          data-testid="workflow-run-inputs"
        >
          {inputs.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd className="break-all">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {proposal.devices.length > 0 && (
        <p className="text-xs" data-testid="workflow-run-devices">
          <span className="text-muted-foreground">Devices: </span>
          {proposal.devices.map((device) => device.name).join(", ")}
        </p>
      )}

      {pending && (
        <>
          <p className="text-xs text-muted-foreground">
            It runs as you, with your permissions, and the workflow may log in to the devices
            it lists. When it has finished, tell the assistant to read the result.
          </p>
          {expired && (
            <Alert>
              <AlertDescription>
                This proposal expired. Ask the assistant again.
              </AlertDescription>
            </Alert>
          )}
          {busy && !isPending && (
            <p className="text-xs text-muted-foreground">
              Wait until the assistant has finished answering, then run it.
            </p>
          )}
          {error && !expired && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={handleRun}
              disabled={expired || busy || isPending}
            >
              {isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              {isPending ? "Starting…" : "Run"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onReject}
              disabled={isPending}
            >
              <X className="size-4" />
              Reject
            </Button>
          </div>
        </>
      )}

      {proposal.state === "rejected" && (
        <p className="text-xs text-muted-foreground">
          Rejected. Nothing was started.
        </p>
      )}

      {proposal.result && (
        <div className="space-y-2" data-testid="workflow-run-started">
          <p className="text-xs">Started as run {proposal.result.runId}.</p>
          {onAskResult && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                proposal.result &&
                onAskResult(proposal.result, proposal.workflow.name)
              }
            >
              Read the result
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
