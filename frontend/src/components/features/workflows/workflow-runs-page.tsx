"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";

import { WorkflowExecutionsPanel } from "./components/workflow-executions-panel";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";

export function WorkflowRunsPage() {
  const router = useRouter();
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowStatus = useWorkflowBuilderStore((state) => state.workflowStatus);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);

  const handleFocusStepOnCanvas = useCallback(
    (nodeId: string) => {
      selectNode(nodeId);
      router.push("/workflows");
    },
    [selectNode, router],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-16 items-center justify-between border-b bg-card px-5">
        <div>
          <h1 className="text-sm font-semibold">{workflowName}</h1>
          <p className="text-xs text-muted-foreground">Workflow runs</p>
        </div>
        <Badge
          variant={
            workflowStatus === "Error"
              ? "destructive"
              : workflowStatus === "Running"
                ? "default"
                : "outline"
          }
        >
          {workflowStatus}
        </Badge>
      </header>
      <main className="flex min-h-0 flex-1">
        <WorkflowExecutionsPanel onFocusNodeOnCanvas={handleFocusStepOnCanvas} />
      </main>
    </div>
  );
}
