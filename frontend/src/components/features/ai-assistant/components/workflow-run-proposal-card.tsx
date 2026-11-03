"use client";

import { Loader2, Play, TriangleAlert, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
  const credentialsQuery = useCredentialsQuery();
  const { mutateAsync, isPending } = useWorkflowRunConfirmMutation();
  const [error, setError] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [freeIpDriver, setFreeIpDriver] = useState("");

  // A confirmed run uses the signed-in user's own credentials, so private ones are fine here.
  const sshLogins = useMemo(
    () =>
      (credentialsQuery.data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh",
      ),
    [credentialsQuery.data?.credentials],
  );

  const pending = proposal.state === "pending";
  const expired = pending && isExpired(proposal.expiresAt);
  const inputs = Object.entries(proposal.inputs);
  const outsideDevices = proposal.devices.filter(
    (device) => !device.inInventory,
  );
  const hasOutside = outsideDevices.length > 0;
  const credentialsChosen = proposal.credentialInputs.every(
    (name) => credentials[name],
  );

  const handleRun = async () => {
    if (isExpired(proposal.expiresAt)) {
      setError("This proposal expired. Ask the assistant again.");
      return;
    }
    if (!credentialsChosen) {
      setError("Choose a credential for every input listed.");
      return;
    }
    setError(null);
    try {
      onResult(
        await mutateAsync({
          token: proposal.token,
          credentials,
          freeIpDriver: hasOutside && freeIpDriver ? freeIpDriver : undefined,
        }),
      );
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
        <ul
          className="space-y-0.5 text-xs"
          data-testid="workflow-run-devices"
          aria-label="Devices"
        >
          {proposal.devices.map((device) => (
            <li key={device.ip} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{device.name}</span>
              <span className="font-mono text-muted-foreground">
                {device.ip}
              </span>
              {!device.inInventory && (
                <span className="rounded border border-destructive px-1 text-[10px] text-destructive">
                  not in the inventory
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {pending && hasOutside && (
        <Alert variant="destructive" data-testid="workflow-run-outside-warning">
          <TriangleAlert className="size-4" />
          <AlertDescription>
            {outsideDevices.map((device) => device.ip).join(", ")}{" "}
            {outsideDevices.length === 1 ? "is" : "are"} not in the inventory.
            The workflow will log in to{" "}
            {outsideDevices.length === 1 ? "it" : "them"} with your credential.
            Run only if you know this address.
          </AlertDescription>
        </Alert>
      )}

      {pending && (
        <>
          <p className="text-xs text-muted-foreground">
            It runs as you, with your permissions, and the workflow may log in
            to the devices it lists using the credential you choose. When it has
            finished, tell the assistant to read the result.
          </p>
          {proposal.credentialInputs.map((name) => (
            <div key={name} className="space-y-1">
              <p className="text-xs text-muted-foreground">
                Your credential for <span className="font-mono">{name}</span>
              </p>
              <Select
                value={credentials[name] ?? ""}
                onValueChange={(value) =>
                  setCredentials((previous) => ({ ...previous, [name]: value }))
                }
                disabled={isPending}
              >
                <SelectTrigger aria-label={`Credential for ${name}`}>
                  <SelectValue placeholder="Choose a credential" />
                </SelectTrigger>
                <SelectContent>
                  {sshLogins.length === 0 ? (
                    <div className="px-2 py-1.5 text-xs text-muted-foreground">
                      No SSH logins found. Add one in Settings → Credentials.
                    </div>
                  ) : (
                    sshLogins.map((credential) => (
                      <SelectItem key={credential.id} value={credential.name}>
                        {credential.name} ({credential.username})
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
          ))}
          {hasOutside && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                Device type for the address outside the inventory (optional; the
                workflow&apos;s default applies without it)
              </p>
              <Select
                value={freeIpDriver}
                onValueChange={setFreeIpDriver}
                disabled={isPending}
              >
                <SelectTrigger aria-label="Device type">
                  <SelectValue placeholder="Use the workflow's default" />
                </SelectTrigger>
                <SelectContent>
                  {proposal.driverChoices.map((choice) => (
                    <SelectItem key={choice} value={choice}>
                      {choice}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
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
              disabled={expired || busy || isPending || !credentialsChosen}
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
