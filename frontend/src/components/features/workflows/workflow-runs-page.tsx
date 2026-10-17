"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Play, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { DataSharingNotice } from "@/components/features/ai-assistant/components/data-sharing-notice";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import { useAssistantSessionOpen } from "@/components/features/ai-assistant/hooks/use-assistant-session-open";
import type {
  AssistantContext,
  ConversationScope,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";

import { WorkflowExecutionsPanel } from "./components/workflow-executions-panel";
import { useWorkflowBuilderStore } from "./hooks/use-workflow-builder-store";

const ACTIVE_RUN_STATUSES = new Set(["pending", "running", "paused"]);

const ASSISTANT_SESSION_KEY = "run_viewer";
const ASSISTANT_SCOPE: ConversationScope = {
  surface: "run_viewer",
  subjectKey: "",
};

export function WorkflowRunsPage() {
  const router = useRouter();
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowStatus = useWorkflowBuilderStore(
    (state) => state.workflowStatus,
  );
  const activeRunId = useWorkflowBuilderStore((state) => state.activeRunId);
  const selectNode = useWorkflowBuilderStore((state) => state.selectNode);
  const { data: activeRun } = useWorkflowRunQuery(activeRunId);

  // workflowStatus is a static store field set once when a run is triggered
  // (markRunning()) and never transitioned back afterward, so it goes stale
  // as "Running" forever. Prefer the polled run status when available so the
  // badge reflects actual completion.
  let displayLabel: string = workflowStatus;
  let displayVariant: "default" | "destructive" | "outline" =
    workflowStatus === "Error"
      ? "destructive"
      : workflowStatus === "Running"
        ? "default"
        : "outline";
  if (activeRun && ACTIVE_RUN_STATUSES.has(activeRun.status)) {
    displayLabel = "Running";
    displayVariant = "default";
  } else if (activeRun?.status === "success") {
    displayLabel = "Success";
    displayVariant = "outline";
  } else if (activeRun?.status === "failed") {
    displayLabel = "Failed";
    displayVariant = "destructive";
  } else if (activeRun?.status === "cancelled") {
    displayLabel = "Cancelled";
    displayVariant = "outline";
  }

  // AI assistant: read-only run explainer, rendered only while the user has it enabled.
  const assistantAvailable = useAiAssistantAvailable();
  const {
    open: assistantOpen,
    setOpen: setAssistantOpen,
    toggle: toggleAssistant,
  } = useAssistantSessionOpen(ASSISTANT_SESSION_KEY);
  const getAssistantContext = useCallback(
    (): AssistantContext => ({ surface: "run_viewer", run_id: activeRunId }),
    [activeRunId],
  );

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
        <div className="flex items-center gap-3">
          {assistantAvailable ? (
            <Button
              variant={assistantOpen ? "default" : "outline"}
              onClick={toggleAssistant}
            >
              <Sparkles className="size-4" />
              AI Assistant
            </Button>
          ) : null}
          <Badge variant={displayVariant}>{displayLabel}</Badge>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
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
            <WorkflowExecutionsPanel
              onFocusNodeOnCanvas={handleFocusStepOnCanvas}
            />
          )}
        </main>
        {assistantAvailable && assistantOpen ? (
          <aside
            className="flex w-[420px] shrink-0 flex-col gap-3 border-l bg-card p-4"
            aria-label="AI Assistant"
          >
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Sparkles className="size-4" />
                AI Assistant
              </h2>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => setAssistantOpen(false)}
                aria-label="Close assistant"
              >
                <X className="size-4" />
              </Button>
            </div>
            <DataSharingNotice />
            <div className="min-h-0 flex-1">
              <AssistantPanel
                sessionKey={ASSISTANT_SESSION_KEY}
                conversationScope={ASSISTANT_SCOPE}
                placeholder={
                  activeRunId
                    ? `Ask about run #${activeRunId}, e.g. why did it fail?`
                    : "Open a run, then ask why it failed or what a step did…"
                }
                getContext={getAssistantContext}
              />
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
