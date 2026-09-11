"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function GitRepositoryStatusBadge({
  isActive,
  className,
}: {
  isActive: boolean;
  className?: string;
}) {
  return (
    <Badge
      className={cn(
        isActive ? "bg-success text-success-foreground" : "bg-muted text-muted-foreground",
        className,
      )}
      variant="secondary"
    >
      {isActive ? "Active" : "Inactive"}
    </Badge>
  );
}
