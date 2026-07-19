"use client";

import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { CanvasGroup } from "../types/workflow-canvas";

interface CanvasGroupBreadcrumbProps {
  groups: CanvasGroup[];
}

export function CanvasGroupBreadcrumb({ groups }: CanvasGroupBreadcrumbProps) {
  const activeGroupId = useWorkflowBuilderStore((state) => state.activeGroupId);
  const exitToParent = useWorkflowBuilderStore((state) => state.exitToParent);

  if (!activeGroupId) {
    return null;
  }

  const activeGroup = groups.find((group) => group.id === activeGroupId);

  return (
    <div className="flex shrink-0 items-center gap-2 border-b bg-card px-4 py-2 text-sm">
      <Button
        className="gap-1.5"
        onClick={exitToParent}
        size="sm"
        variant="outline"
      >
        <ChevronLeft className="size-3.5" aria-hidden />
        Go to upper group
      </Button>
      <span className="text-muted-foreground">Workflow root</span>
      <span className="text-muted-foreground">›</span>
      <span className="font-medium">{activeGroup?.title ?? "Group"}</span>
    </div>
  );
}
