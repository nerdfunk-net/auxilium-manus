import type { CredentialStatus, CredentialType } from "../types";

export function formatValidUntil(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString();
}

export function toDateInputValue(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(0, 10);
  }
  return date.toISOString().slice(0, 10);
}

const STATUS_LABELS: Record<CredentialStatus, string> = {
  active: "Active",
  expiring: "Expiring soon",
  expired: "Expired",
  unknown: "Unknown",
};

export function credentialStatusLabel(status: CredentialStatus): string {
  return STATUS_LABELS[status];
}

/** Credential types selectable in the Credentials UI. "tacacs" exists on the
 * backend but is created programmatically by other features (TACACS device
 * auth) — not offered here. */
export const SELECTABLE_CREDENTIAL_TYPES: readonly CredentialType[] = [
  "ssh",
  "ssh_key",
  "token",
  "generic",
];

const TYPE_LABELS: Record<CredentialType, string> = {
  ssh: "SSH Login",
  ssh_key: "SSH Key",
  token: "Token",
  generic: "Basic Auth (Username + Password)",
  tacacs: "TACACS",
};

export function credentialTypeLabel(type: CredentialType): string {
  return TYPE_LABELS[type] ?? type;
}
