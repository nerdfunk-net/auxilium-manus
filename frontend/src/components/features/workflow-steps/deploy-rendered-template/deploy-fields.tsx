"use client";

import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";

const MIN_READ_TIMEOUT = 5;
const MAX_READ_TIMEOUT = 600;

export interface DeployCredentialFieldsProps {
  credentialReference: string;
  onCredentialChange: (value: string) => void;
}

export function DeployCredentialFields({
  credentialReference,
  onCredentialChange,
}: DeployCredentialFieldsProps) {
  const { data, isLoading } = useCredentialsQuery();
  const sshCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">credential_reference</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          credential_ref
        </Badge>
      </div>

      {isLoading ? (
        <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
      ) : sshCredentials.length === 0 && !credentialReference ? (
        <p className="text-[11px] text-warning-foreground">
          No SSH credentials in Settings → Credentials
        </p>
      ) : (
        <Select value={credentialReference} onValueChange={onCredentialChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select SSH credential" />
          </SelectTrigger>
          <SelectContent>
            {credentialReference &&
              !sshCredentials.some((credential) => credential.name === credentialReference) && (
                <SelectItem value={credentialReference} disabled>
                  {credentialReference} (not accessible)
                </SelectItem>
              )}
            {sshCredentials.map((credential) => (
              <SelectItem key={credential.id} value={credential.name}>
                {credential.name} ({credential.username})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

export interface DeployReadTimeoutFieldsProps {
  readTimeout: number;
  onReadTimeoutChange: (value: string) => void;
}

export function DeployReadTimeoutFields({
  readTimeout,
  onReadTimeoutChange,
}: DeployReadTimeoutFieldsProps) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">read_timeout</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          integer
        </Badge>
      </div>
      <Input
        type="number"
        min={MIN_READ_TIMEOUT}
        max={MAX_READ_TIMEOUT}
        value={readTimeout}
        onChange={(event) => onReadTimeoutChange(event.target.value)}
        className="h-8 font-mono text-xs"
      />
      <p className="text-[11px] text-muted-foreground">
        Seconds to wait for each command&apos;s response. Raise this if a &ldquo;Pattern not
        detected&rdquo; timeout appears for commands with slow or multi-line output.
      </p>
    </div>
  );
}
