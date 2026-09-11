"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { gitCategoryLabel } from "../utils/git-repository-utils";

const CATEGORY_SHORT_LABELS: Record<string, string> = {
  workflow_steps: "Workflow steps",
  workflows: "Version control",
  device_configs: "Device configs",
  cicd_pipeline: "CI/CD Pipeline",
};

export function GitRepositoryCategoryBadge({
  category,
  className,
}: {
  category: string;
  className?: string;
}) {
  return (
    <Badge
      className={cn("bg-muted text-muted-foreground", className)}
      variant="secondary"
      title={gitCategoryLabel(category)}
    >
      {CATEGORY_SHORT_LABELS[category] ?? category}
    </Badge>
  );
}
