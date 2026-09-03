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

import { RunParamSourceField, type RunParamSourceMode } from "./run-param-source-field";

interface SshCredentialFieldProps {
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

/**
 * The credential picker shared by every SSH step. In "Fixed" mode it's a
 * dropdown of the user's SSH credentials (written to `credential_reference`);
 * in "Run parameter" mode the vault name is taken at dispatch from the named
 * workflow run parameter (`credential_source` / `credential_param`), resolved
 * per triggering user — see doc/SCHEDULES.md.
 */
export function SshCredentialField({ config, onChange }: SshCredentialFieldProps) {
  const { data, isLoading } = useCredentialsQuery();
  const sshCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const credentialReference =
    typeof config.credential_reference === "string" ? config.credential_reference : "";
  const mode: RunParamSourceMode =
    config.credential_source === "run_param" ? "run_param" : "fixed";
  const paramName =
    typeof config.credential_param === "string" ? config.credential_param : "";

  const setCredential = useCallback(
    (value: string) => onChange({ ...config, credential_reference: value }),
    [config, onChange],
  );
  const setMode = useCallback(
    (next: RunParamSourceMode) => onChange({ ...config, credential_source: next }),
    [config, onChange],
  );
  const setParamName = useCallback(
    (name: string) => onChange({ ...config, credential_param: name }),
    [config, onChange],
  );

  return (
    <RunParamSourceField
      label="Credential"
      refKind="credential"
      mode={mode}
      paramName={paramName}
      onModeChange={setMode}
      onParamNameChange={setParamName}
    >
      {isLoading ? (
        <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
      ) : sshCredentials.length === 0 && !credentialReference ? (
        <p className="text-[11px] text-warning-foreground">
          No SSH credentials in Settings → Credentials
        </p>
      ) : (
        <Select value={credentialReference} onValueChange={setCredential}>
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
    </RunParamSourceField>
  );
}
