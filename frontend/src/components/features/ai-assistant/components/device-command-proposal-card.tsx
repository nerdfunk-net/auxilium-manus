"use client";

import { Loader2, Play, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useDeviceCommandMutation } from "../hooks/use-device-command";
import type {
  DeviceCommandProposal,
  DeviceCommandResult,
} from "../types/ai-assistant";

interface DeviceCommandProposalCardProps {
  proposal: DeviceCommandProposal;
  onResult: (result: DeviceCommandResult) => void;
  onReject: () => void;
  /** The assistant is still answering: Run waits, so the answer to the run can follow it. */
  busy?: boolean;
}

const GENERIC_ERROR = "The command could not be run";

function isExpired(expiresAt: number): boolean {
  return Date.now() / 1000 >= expiresAt;
}

/**
 * Read-only commands the assistant wants run on one device. The device and the exact commands are
 * shown as plain text (never interpreted as markup); the server runs what its signed token says,
 * as the signed-in user, with the SSH login chosen here. Nothing runs until Run is clicked.
 */
export function DeviceCommandProposalCard({
  proposal,
  onResult,
  onReject,
  busy = false,
}: DeviceCommandProposalCardProps) {
  const credentialsQuery = useCredentialsQuery();
  const { mutateAsync, isPending } = useDeviceCommandMutation();
  const [credentialId, setCredentialId] = useState("");
  const [networkDriver, setNetworkDriver] = useState("");
  const [error, setError] = useState<string | null>(null);

  // A confirmed run uses the signed-in user's own login, so private credentials are fine here.
  const sshLogins = useMemo(
    () =>
      (credentialsQuery.data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh",
      ),
    [credentialsQuery.data?.credentials],
  );

  const pending = proposal.state === "pending";
  // The inventory's platform names no SSH driver: the user chooses the device type, like a
  // driver override on a workflow step. The assistant has no say in it.
  const needsDriver = !proposal.driverKnown;
  const expired = pending && isExpired(proposal.expiresAt);

  const handleRun = async () => {
    if (
      !credentialId ||
      (needsDriver && !networkDriver) ||
      isExpired(proposal.expiresAt)
    ) {
      setError("This proposal expired. Ask the assistant again.");
      return;
    }
    setError(null);
    try {
      onResult(
        await mutateAsync({
          token: proposal.token,
          credentialId: Number(credentialId),
          networkDriver: needsDriver ? networkDriver : undefined,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : GENERIC_ERROR);
    }
  };

  return (
    <div
      className="space-y-2 rounded-md border bg-card p-3"
      data-testid="device-command-proposal"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">
          Run on <span className="font-semibold">{proposal.device.name}</span>
        </p>
        <Badge variant="outline" className="shrink-0 font-mono">
          {proposal.device.host}
        </Badge>
      </div>
      <pre
        className="overflow-x-auto rounded border bg-muted/30 p-2 font-mono text-xs"
        data-testid="device-command-list"
      >
        {proposal.commands.map((command) => `$ ${command}`).join("\n")}
      </pre>

      {pending && (
        <>
          <p className="text-xs text-muted-foreground">
            Read-only: nothing on the device is changed. It runs as you, with
            the SSH login you choose. After it runs, the assistant reads the
            output (secrets are hidden).
          </p>
          {expired && (
            <Alert>
              <AlertDescription>
                This proposal expired. Ask the assistant again.
              </AlertDescription>
            </Alert>
          )}
          <Select
            value={credentialId}
            onValueChange={setCredentialId}
            disabled={isPending}
          >
            <SelectTrigger aria-label="SSH login">
              <SelectValue placeholder="Choose an SSH login" />
            </SelectTrigger>
            <SelectContent>
              {sshLogins.length === 0 ? (
                <div className="px-2 py-1.5 text-xs text-muted-foreground">
                  No SSH logins found. Add one in Settings → Credentials.
                </div>
              ) : (
                sshLogins.map((credential) => (
                  <SelectItem key={credential.id} value={String(credential.id)}>
                    {credential.name} ({credential.username})
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
          {needsDriver && (
            <>
              <p className="text-xs text-muted-foreground">
                The inventory does not say which device type{" "}
                {proposal.device.name} is
                {proposal.device.platform
                  ? ` (platform: ${proposal.device.platform})`
                  : ""}
                . Choose it so the right SSH driver is used.
              </p>
              <Select
                value={networkDriver}
                onValueChange={setNetworkDriver}
                disabled={isPending}
              >
                <SelectTrigger aria-label="Device type">
                  <SelectValue placeholder="Choose the device type" />
                </SelectTrigger>
                <SelectContent>
                  {proposal.driverChoices.map((choice) => (
                    <SelectItem key={choice} value={choice}>
                      {choice}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
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
              disabled={
                !credentialId ||
                (needsDriver && !networkDriver) ||
                expired ||
                busy ||
                isPending
              }
            >
              {isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              {isPending ? "Running…" : "Run"}
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
          Rejected. Nothing was run.
        </p>
      )}

      {proposal.result && (
        <div className="space-y-2">
          {proposal.result.error && (
            <Alert variant="destructive">
              <AlertDescription>{proposal.result.error}</AlertDescription>
            </Alert>
          )}
          {proposal.result.output && (
            <pre
              className="max-h-72 overflow-auto rounded border bg-muted/30 p-2 font-mono text-xs whitespace-pre"
              data-testid="device-command-output"
            >
              {proposal.result.output}
            </pre>
          )}
          {proposal.result.truncated && (
            <p className="text-xs text-muted-foreground">
              The output was cut because it is very long.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
