"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { WorkflowExecutionsPanel } from "./components/workflow-executions-panel";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";

export function WorkflowRunsPage() {
  const router = useRouter();
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
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
      <main className="flex min-h-0 flex-1 flex-col">
        {!workflowId ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center text-muted-foreground">
            <Play className="size-10 opacity-30" aria-hidden />
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">
                No saved workflow
              </p>
              <p className="text-sm">
                Save a workflow first, then click Run to see executions here.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/workflows">Open workflow editor</Link>
            </Button>
          </div>
        ) : (
          <WorkflowExecutionsPanel onFocusNodeOnCanvas={handleFocusStepOnCanvas} />
        )}
      </main>
    </div>
  );
}
