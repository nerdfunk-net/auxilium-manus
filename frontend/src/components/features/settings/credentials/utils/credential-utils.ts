import type { CredentialStatus } from "../types";

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
