import { ApiError } from "@/hooks/use-api";

import type { CredentialDependant } from "../types";

export const CREDENTIAL_IN_USE_CODE = "credential_in_use";

const KIND_LABELS: Record<string, string> = {
  git_repository: "Git repository",
  secret_manager: "Secret manager connection",
  template: "Template",
  source: "Source",
  mail_settings: "Mail settings",
  workflow: "Workflow",
};

export function describeDependantKind(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

function isDependant(value: unknown): value is CredentialDependant {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    typeof item.kind === "string" &&
    typeof item.id === "number" &&
    typeof item.name === "string"
  );
}

/** The dependants of a "credential is still in use" 409, or null for any other error. */
export function dependantsFromError(error: unknown): CredentialDependant[] | null {
  if (!(error instanceof ApiError) || error.detail?.code !== CREDENTIAL_IN_USE_CODE) {
    return null;
  }
  const raw = error.detail.dependants;
  return Array.isArray(raw) ? raw.filter(isDependant) : [];
}
