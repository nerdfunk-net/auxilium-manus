"use client";

import { Activity, Clock, FileText } from "lucide-react";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

export function WorkflowRunControls() {
  const lastAction = useWorkflowBuilderStore((state) => state.lastAction);

  return (
    <footer className="flex h-12 items-center justify-between border-t bg-card px-5 text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <Activity className="size-4" />
        {lastAction}
      </div>
      <div className="flex items-center gap-5">
        <span className="flex items-center gap-2">
          <Clock className="size-4" />
          No real execution connected
        </span>
        <span className="flex items-center gap-2">
          <FileText className="size-4" />
          Metadata and content outputs are separated
        </span>
      </div>
    </footer>
  );
}
