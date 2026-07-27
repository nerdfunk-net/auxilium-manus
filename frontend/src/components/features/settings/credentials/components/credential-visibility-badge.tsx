"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { CredentialVisibility } from "../types";

const VISIBILITY_CLASSES: Record<CredentialVisibility, string> = {
  global: "bg-slate-100 text-slate-700",
  private: "bg-blue-100 text-blue-800",
};

const VISIBILITY_LABELS: Record<CredentialVisibility, string> = {
  global: "Global",
  private: "Private",
};

export function CredentialVisibilityBadge({
  visibility,
  className,
}: {
  visibility: CredentialVisibility;
  className?: string;
}) {
  return (
    <Badge className={cn(VISIBILITY_CLASSES[visibility], className)} variant="secondary">
      {VISIBILITY_LABELS[visibility]}
    </Badge>
  );
}
