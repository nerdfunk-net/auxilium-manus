"use client";

import { ChevronDown, ChevronRight, MapPin, ScrollText } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StepResultViewer } from "./step-result-viewer";
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
  runId: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenModal: () => void;
  onFocusCanvas?: (nodeId: string) => void;
  isFanOutRun?: boolean;
}

export function StepResultRow({
  step,
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
            <p className="mt-0.5 line-clamp-1 text-xs text-red-500">{step.error_message}</p>
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
          <StepResultViewer output={step.output} errorMessage={step.error_message} compact runId={runId} />
        </div>
      ) : null}
    </div>
  );
}
