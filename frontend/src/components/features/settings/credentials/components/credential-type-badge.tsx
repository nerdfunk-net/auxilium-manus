"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { CredentialType } from "../types";
import { credentialTypeLabel } from "../utils/credential-utils";

export function CredentialTypeBadge({
  type,
  className,
}: {
  type: CredentialType;
  className?: string;
}) {
  return (
    <Badge className={cn("bg-muted text-muted-foreground", className)} variant="secondary">
      {credentialTypeLabel(type)}
    </Badge>
  );
}
