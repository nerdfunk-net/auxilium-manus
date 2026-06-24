"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { CredentialStatus } from "../types";
import { credentialStatusLabel } from "../utils/credential-utils";

const STATUS_CLASSES: Record<CredentialStatus, string> = {
  active: "bg-emerald-100 text-emerald-800",
  expiring: "bg-amber-100 text-amber-800",
  expired: "bg-red-100 text-red-800",
  unknown: "bg-slate-100 text-slate-600",
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
