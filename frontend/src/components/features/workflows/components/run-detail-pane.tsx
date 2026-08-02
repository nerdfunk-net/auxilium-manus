"use client";

import { useCallback, useMemo, useState } from "react";
import { Ban, Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useWorkflowRunQuery } from "@/hooks/queries/use-workflow-run-query";
import { useCancelRunMutation } from "@/hooks/queries/use-workflow-run-mutations";
import { RunStatusIcon, formatTime } from "./run-status-icon";
import { ApprovalBanner, FanOutBanner } from "./run-banners";
import { StepErrorAlert } from "./step-error-alert";
import { StepResultRow } from "./step-result-row";
import { StepLogsModal } from "./step-logs-modal";
import { detectRunFanOut } from "../utils/step-result-status";
import type { WorkflowStepResult } from "../types/workflow-runs";

interface RunDetailPaneProps {
  runId: number | null;
  workflowId: number | null;
  onFocusCanvas?: (nodeId: string) => void;
}

export function RunDetailPane({ runId, workflowId, onFocusCanvas }: RunDetailPaneProps) {
  const [logsStep, setLogsStep] = useState<WorkflowStepResult | null>(null);
  const [expandedStepId, setExpandedStepId] = useState<number | null>(null);

  const { data, isLoading } = useWorkflowRunQuery(runId);
  const cancelRun = useCancelRunMutation(workflowId);

  const fanOutInfo = useMemo(() => (data ? detectRunFanOut(data.step_results) : null), [data]);

  const toggleStep = useCallback((stepId: number) => {
    setExpandedStepId((current) => (current === stepId ? null : stepId));
  }, []);

  if (runId == null) {
    return (
      <div className="flex h-full items-center justify-center text-center text-muted-foreground">
        <div>
          <Play className="mx-auto mb-2 size-8 opacity-30" />
          <p className="text-sm">Select a run to view its details.</p>
        </div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const canCancel = data.status === "pending" || data.status === "running" || data.status === "paused";

  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b bg-background px-6 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <RunStatusIcon status={data.status} />
            <p className="text-sm font-semibold">Run #{data.id}</p>
            <span className="font-mono text-xs text-muted-foreground">{data.uuid}</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {data.triggered_by_username ?? "unknown"} · started {formatTime(data.created_at)}
            {data.finished_at ? ` · finished ${formatTime(data.finished_at)}` : ""}
          </p>
        </div>
        {canCancel ? (
          <Button
            variant="outline"
            size="sm"
            className="h-7 shrink-0 gap-1 text-xs"
            disabled={cancelRun.isPending}
            onClick={() => cancelRun.mutate(data.id)}
          >
            <Ban className="size-3.5" />
            Cancel
          </Button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {data.error_message ? (
          <div className="border-b px-4 py-3">
            <StepErrorAlert
              message={data.error_message}
              category={data.error_category}
              errorId={data.error_id}
            />
          </div>
        ) : null}
        {data.approval_state?.awaiting ? (
          <ApprovalBanner approvalState={data.approval_state} runId={data.id} workflowId={workflowId} />
        ) : null}
        {fanOutInfo ? <FanOutBanner info={fanOutInfo} /> : null}

        {data.step_results.length === 0 ? (
          <div className="px-6 py-4 text-xs text-muted-foreground">No step results yet.</div>
        ) : (
          <div className="divide-y">
            {data.step_results.map((step) => (
              <StepResultRow
                key={step.id}
                step={step}
                allSteps={data.step_results}
                runId={data.id}
                expanded={expandedStepId === step.id}
                onToggle={() => toggleStep(step.id)}
                onOpenModal={() => setLogsStep(step)}
                onFocusCanvas={onFocusCanvas}
                isFanOutRun={fanOutInfo !== null}
              />
            ))}
          </div>
        )}
      </div>
      <StepLogsModal step={logsStep} runId={data.id} onClose={() => setLogsStep(null)} />
    </>
  );
}
