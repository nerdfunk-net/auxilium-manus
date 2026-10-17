"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { CredentialStorageBackend } from "../types";

const BACKEND_CLASSES: Record<CredentialStorageBackend, string> = {
  local: "bg-muted text-muted-foreground",
  vault: "bg-primary/10 text-primary",
};

const BACKEND_LABELS: Record<CredentialStorageBackend, string> = {
  local: "Local",
  vault: "Vault",
};

export function CredentialBackendBadge({
  backend,
  className,
}: {
  backend: CredentialStorageBackend;
  className?: string;
}) {
  return (
    <Badge className={cn(BACKEND_CLASSES[backend], className)} variant="secondary">
      {BACKEND_LABELS[backend]}
    </Badge>
  );
}
