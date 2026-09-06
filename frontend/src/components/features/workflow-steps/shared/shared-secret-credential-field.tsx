"use client";

import { useCallback, useMemo } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { sharedSecretAlgorithmLabel } from "@/lib/shared-secret-algorithms";

interface SharedSecretCredentialFieldProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

/**
 * Credential picker for the Encrypt/Decrypt Attribute steps. Lists the vault's
 * `shared_secret` credentials and stores the chosen one by **name** in
 * `credential_reference` — the passphrase itself never enters the workflow.
 */
export function SharedSecretCredentialField({
  config,
  onChange,
}: SharedSecretCredentialFieldProps) {
  const { data, isLoading } = useCredentialsQuery();
  const sharedSecrets = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) =>
          credential.type === "shared_secret" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const credentialReference =
    typeof config.credential_reference === "string" ? config.credential_reference : "";

  const selected = useMemo(
    () => sharedSecrets.find((credential) => credential.name === credentialReference) ?? null,
    [sharedSecrets, credentialReference],
  );

  const setCredential = useCallback(
    (value: string) => onChange({ ...config, credential_reference: value }),
    [config, onChange],
  );

  return (
    <div className="space-y-1.5">
      <span className="font-mono text-xs font-medium">credential_reference</span>
      {isLoading ? (
        <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
      ) : sharedSecrets.length === 0 && !credentialReference ? (
        <p className="text-[11px] text-warning-foreground">
          No shared-secret credentials in Settings → Credential vault
        </p>
      ) : (
        <Select value={credentialReference} onValueChange={setCredential}>
          <SelectTrigger className="h-8 text-xs">
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
      )}
      {selected ? (
        <p className="text-[11px] text-muted-foreground">
          Default algorithm: {sharedSecretAlgorithmLabel(selected.algorithm)}
        </p>
      ) : null}
    </div>
  );
}
