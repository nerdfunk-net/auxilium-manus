"use client";

import { useMemo } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useCredentialsQuery } from "../hooks/use-credentials-query";
import type { CredentialType } from "../types";

interface CredentialSelectProps {
  id: string;
  value: number | null;
  onChange: (credentialId: number | null) => void;
  credentialType?: CredentialType;
  disabled?: boolean;
  placeholder?: string;
}

const TYPE_LABEL: Partial<Record<CredentialType, string>> = {
  token: "token",
  ssh: "SSH login",
  ssh_key: "SSH key",
};

/**
 * Picks a credential from the vault by numeric id. Only global credentials are
 * selectable — source integrations run in the background, not as the signed-in
 * user, so private credentials are not readable.
 */
export function CredentialSelect({
  id,
  value,
  onChange,
  credentialType = "token",
  disabled,
  placeholder = "Select a credential",
}: CredentialSelectProps) {
  const { data } = useCredentialsQuery();

  const matching = useMemo(
    () => (data?.credentials ?? []).filter((cred) => cred.type === credentialType),
    [data?.credentials, credentialType],
  );
  const hasPrivateOnly =
    matching.length > 0 && matching.every((cred) => cred.visibility !== "global");
  const typeLabel = TYPE_LABEL[credentialType] ?? "matching";

  return (
    <div className="space-y-2">
      <Select
        value={value != null ? String(value) : ""}
        onValueChange={(next) => onChange(next ? Number(next) : null)}
        disabled={disabled}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {matching.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              No {typeLabel} credentials found. Add one in Settings → Credentials.
            </div>
          ) : (
            matching.map((cred) => (
              <SelectItem
                key={cred.id}
                value={String(cred.id)}
                disabled={cred.visibility !== "global"}
              >
                {cred.name} ({cred.username})
                {cred.visibility !== "global" ? " — private, must be global" : ""}
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground">
        Only <strong>global</strong> credentials are usable here — source
        integrations run in the background, not as the signed-in user, so private
        credentials are not readable.
        {hasPrivateOnly
          ? " Edit the credential in Settings → Credentials and turn on “Make this credential global”."
          : ""}
      </p>
    </div>
  );
}
