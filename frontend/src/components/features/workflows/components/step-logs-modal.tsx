"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StepResultViewer } from "./step-result-viewer";
import { StepStatusBadge } from "./step-status-badge";
import { deriveStepDisplayStatus } from "../utils/step-result-status";
import type { WorkflowStepResult } from "../types/workflow-runs";

export function StepLogsModal({
  step,
  runId,
  onClose,
}: {
  step: WorkflowStepResult | null;
  runId: number;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!step} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col overflow-hidden">
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
        <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto pr-1">
          <StepResultViewer
            output={step?.output ?? null}
            errorMessage={step?.error_message}
            runId={runId}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
