"use client";

import { useMemo } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { sharedSecretAlgorithmLabel } from "@/lib/shared-secret-algorithms";

export type SharedSecretSourceMode = "credential" | "manual";

interface SharedSecretSourceFieldProps {
  idPrefix: string;
  mode: SharedSecretSourceMode;
  onModeChange: (mode: SharedSecretSourceMode) => void;
  credentialReference: string;
  onCredentialReferenceChange: (value: string) => void;
  manualSecret: string;
  onManualSecretChange: (value: string) => void;
}

/**
 * "Shared secret" input for the Encrypt/Decrypt Attribute test dialogs. Mirrors
 * `SharedSecretCredentialField`'s vault lookup (shared_secret-type, non-expired
 * credentials) but lets the operator switch to typing a one-off secret instead,
 * since the test modal isn't necessarily testing the credential the step will
 * use at run time.
 */
export function SharedSecretSourceField({
  idPrefix,
  mode,
  onModeChange,
  credentialReference,
  onCredentialReferenceChange,
  manualSecret,
  onManualSecretChange,
}: SharedSecretSourceFieldProps) {
  const { data, isLoading } = useCredentialsQuery();
  const sharedSecrets = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "shared_secret" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const selected = useMemo(
    () => sharedSecrets.find((credential) => credential.name === credentialReference) ?? null,
    [sharedSecrets, credentialReference],
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label className="text-[11px] text-muted-foreground">Shared secret</Label>
        <Select value={mode} onValueChange={(value) => onModeChange(value as SharedSecretSourceMode)}>
          <SelectTrigger className="h-6 w-[110px] text-[11px]" id={`${idPrefix}-mode`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="credential">Credential</SelectItem>
            <SelectItem value="manual">Type value</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {mode === "credential" ? (
        isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : sharedSecrets.length === 0 && !credentialReference ? (
          <p className="text-[11px] text-warning-foreground">
            No shared-secret credentials in Settings → Credential vault
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={onCredentialReferenceChange}>
            <SelectTrigger className="h-8 text-xs" id={`${idPrefix}-secret-credential`}>
              <SelectValue placeholder="Select shared secret" />
            </SelectTrigger>
            <SelectContent>
              {credentialReference &&
                !sharedSecrets.some((credential) => credential.name === credentialReference) && (
                  <SelectItem value={credentialReference} disabled>
                    {credentialReference} (not accessible)
                  </SelectItem>
                )}
              {sharedSecrets.map((credential) => (
                <SelectItem key={credential.id} value={credential.name}>
                  {credential.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )
      ) : (
        <Input
          id={`${idPrefix}-secret-manual`}
          type="password"
          autoComplete="off"
          className="h-8 font-mono text-xs"
          value={manualSecret}
          onChange={(event) => onManualSecretChange(event.target.value)}
        />
      )}

      {mode === "credential" && selected ? (
        <p className="text-[11px] text-muted-foreground">
          Default algorithm: {sharedSecretAlgorithmLabel(selected.algorithm)}
        </p>
      ) : null}
    </div>
  );
}
