"use client";

import { Activity, CheckCircle2, Clock, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

const ACTIVE_RUN_STATUSES = new Set(["pending", "running", "paused"]);

export function WorkflowRunControls() {
  const workflowStatus = useWorkflowBuilderStore((state) => state.workflowStatus);
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
  const lastAction = useWorkflowBuilderStore((state) => state.lastAction);
  const activeRunId = useWorkflowBuilderStore((state) => state.activeRunId);
  const { data: activeRun } = useWorkflowRunQuery(activeRunId);

  let label: string;
  let Icon: LucideIcon;

  if (workflowStatus === "Error") {
    label = lastAction;
    Icon = XCircle;
  } else if (activeRun && ACTIVE_RUN_STATUSES.has(activeRun.status)) {
    label = "Running";
    Icon = Activity;
  } else if (activeRun?.status === "success") {
    label = "Last run was successful";
    Icon = CheckCircle2;
  } else if (activeRun?.status === "failed") {
    label = "Last run failed";
    Icon = XCircle;
  } else if (activeRun?.status === "cancelled") {
    label = "Last run was cancelled";
    Icon = XCircle;
  } else {
    label = workflowStatus;
    Icon = Clock;
  }

  const statusText = isDirty && label !== "Draft" ? `${label} · Draft` : label;

  return (
    <footer className="flex h-12 items-center border-t bg-card px-5 text-xs text-muted-foreground">
      <span className="flex items-center gap-2">
        <Icon className="size-4" />
        {statusText}
      </span>
    </footer>
  );
}
