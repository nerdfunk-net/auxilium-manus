"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RunEventsLog } from "./run-events-log";
import { StepResultViewer } from "./step-result-viewer";
import { StepStatusBadge } from "./step-status-badge";
import { deriveStepDisplayStatus } from "../utils/step-result-status";
import type { WorkflowRunEvent, WorkflowStepResult } from "../types/workflow-runs";

const NO_EVENTS: readonly WorkflowRunEvent[] = [];

export function StepLogsModal({
  step,
  runId,
  onClose,
  events = NO_EVENTS,
}: {
  step: WorkflowStepResult | null;
  runId: number;
  onClose: () => void;
  /** Live events for this step only. */
  events?: readonly WorkflowRunEvent[];
}) {
  return (
    <Dialog open={!!step} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex h-[85vh] max-w-3xl flex-col overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle>{step?.step_name ?? "Step result"}</DialogTitle>
          <DialogDescription className="space-y-1">
            <span className="block font-mono text-xs">{step?.step_type}</span>
            {step?.step_node_id ? (
              <span className="block break-all font-mono text-xs text-muted-foreground">
                node: {step.step_node_id}
              </span>
            ) : null}
            {step ? (
              <StepStatusBadge status={deriveStepDisplayStatus(step.status, step.output)} />
            ) : null}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 min-w-0 flex-1 space-y-3 overflow-x-hidden overflow-y-auto pr-1">
          <RunEventsLog events={events} />
          <StepResultViewer
            output={step?.output ?? null}
            errorMessage={step?.error_message}
            errorCategory={step?.error_category}
            errorId={step?.error_id}
            runId={runId}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
