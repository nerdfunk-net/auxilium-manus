"use client";

import { ChevronDown, ChevronRight, MapPin, ScrollText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ErrorCategoryIcon } from "./step-error-alert";
import { StepResultViewer } from "./step-result-viewer";
import { StepSummaryTable } from "./step-summary-table";
import { StepStatusBadge } from "./step-status-badge";
import { formatDuration } from "./run-status-icon";
import {
  countOutcomeDevices,
  deriveStepDisplayStatus,
  summarizeCompareData,
  summarizeFanIn,
  summarizeFanOutInventory,
  summarizeLogAttributes,
  summarizeLogMessage,
  summarizeRenderJinjaTemplate,
  summarizeRouteCounts,
} from "../utils/step-result-status";
import type { WorkflowStepResult } from "../types/workflow-runs";

interface StepResultRowProps {
  step: WorkflowStepResult;
  allSteps: WorkflowStepResult[];
  runId: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenModal: () => void;
  onFocusCanvas?: (nodeId: string) => void;
  isFanOutRun?: boolean;
}

export function StepResultRow({
  step,
  allSteps,
  runId,
  expanded,
  onToggle,
  onOpenModal,
  onFocusCanvas,
  isFanOutRun = false,
}: StepResultRowProps) {
  const displayStatus = deriveStepDisplayStatus(step.status, step.output);
  const counts = countOutcomeDevices(step.output);
  const isInventoryStep =
    step.step_type === "get-nautobot-devices" || step.step_type === "get-git-devices";
  const runHint = isInventoryStep
    ? summarizeFanOutInventory(step.output)
    : step.step_type === "fan-in"
      ? summarizeFanIn(step.output)
      : step.step_type === "route-on-attribute"
        ? summarizeRouteCounts(step.output)
        : step.step_type === "render-jinja-template"
          ? summarizeRenderJinjaTemplate(step.output)
          : step.step_type === "compare-data"
            ? summarizeCompareData(step.output)
            : step.step_type === "log-message"
              ? summarizeLogMessage(step.output)
              : step.step_type === "log-attributes"
                ? summarizeLogAttributes(step.output)
                : null;

  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              className="truncate text-left text-sm font-medium hover:underline"
              onClick={onToggle}
            >
              {step.step_name}
            </button>
            <Button
              variant="ghost"
              size="icon"
              className="size-5 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={onOpenModal}
              title="Open in dialog"
            >
              <ScrollText className="size-3.5" />
            </Button>
            {onFocusCanvas ? (
              <Button
                variant="ghost"
                size="icon"
                className="size-5 shrink-0 text-muted-foreground hover:text-foreground"
                onClick={() => onFocusCanvas(step.step_node_id)}
                title="View on canvas"
              >
                <MapPin className="size-3.5" />
              </Button>
            ) : null}
          </div>
          <p className="font-mono text-xs text-muted-foreground">{step.step_type}</p>
          <p className="font-mono text-[11px] text-muted-foreground">{step.step_node_id}</p>
          {runHint ? <p className="mt-0.5 text-[11px] text-muted-foreground">{runHint}</p> : null}
          {counts.totalOutcomes > 0 ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {counts.success} succeeded
              {counts.failure > 0 ? ` · ${counts.failure} failed` : ""}
              {isFanOutRun && !isInventoryStep && step.step_type !== "fan-in"
                ? " · via fan-out"
                : ""}
            </p>
          ) : null}
          {step.error_message && !expanded ? (
            <p className="mt-0.5 flex items-center gap-1 text-xs text-red-500">
              <ErrorCategoryIcon category={step.error_category} className="size-3 shrink-0" />
              <span className="line-clamp-1">{step.error_message}</span>
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={onToggle} className="flex items-center gap-2">
            <StepStatusBadge status={displayStatus} />
            <span className="text-xs tabular-nums text-muted-foreground">
              {formatDuration(step.started_at, step.finished_at)}
            </span>
            {expanded ? (
              <ChevronDown className="size-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="size-4 text-muted-foreground" />
            )}
          </button>
        </div>
      </div>
      {expanded ? (
        <div className="mt-3 min-w-0 overflow-x-hidden border-t pt-3">
          {step.step_type === "show-summary" ? (
            <StepSummaryTable steps={allSteps} />
          ) : (
            <StepResultViewer
              output={step.output}
              errorMessage={step.error_message}
              errorCategory={step.error_category}
              errorId={step.error_id}
              compact
              runId={runId}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}
