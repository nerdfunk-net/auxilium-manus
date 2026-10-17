"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { CredentialStatus } from "../types";
import { credentialStatusLabel } from "../utils/credential-utils";

const STATUS_CLASSES: Record<CredentialStatus, string> = {
  active: "bg-success text-success-foreground",
  expiring: "bg-warning text-warning-foreground",
  expired: "bg-error text-error-foreground",
  unknown: "bg-muted text-muted-foreground",
};

export function CredentialStatusBadge({
  status,
  className,
}: {
  status: CredentialStatus;
  className?: string;
}) {
  return (
    <Badge className={cn(STATUS_CLASSES[status], className)} variant="secondary">
      {credentialStatusLabel(status)}
    </Badge>
  );
}
