"use client";

import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  MapPin,
  Play,
  ScrollText,
  Split,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import { useWorkflowRunsQuery } from "@/hooks/queries/use-workflow-runs-query";
import { useCancelRunMutation } from "@/hooks/queries/use-workflow-run-mutations";
import { WorkflowRunFiltersBar } from "./workflow-run-filters-bar";
import { StepResultViewer } from "./step-result-viewer";
import {
  EMPTY_WORKFLOW_RUN_FILTERS,
  hasActiveWorkflowRunFilters,
} from "../types/workflow-run-filters";
import type { WorkflowRunListFilters } from "../types/workflow-run-filters";
import type {
  WorkflowRunDetail,
  WorkflowRunStatus,
  WorkflowStepResult,
  WorkflowRunSummary,
} from "../types/workflow-runs";
import {
  countOutcomeDevices,
  deriveStepDisplayStatus,
  detectRunFanOut,
  summarizeFanIn,
  summarizeFanOutInventory,
  summarizeRouteCounts,
  summarizeRenderJinjaTemplate,
  summarizeCompareData,
  summarizeShowAttributes,
  summarizeWorkflowLogMessage,
  type DerivedStepStatus,
  type FanOutInfo,
} from "../utils/step-result-status";

function formatDuration(started: string | null, finished: string | null): string {
  if (!started) return "—";
  const start = new Date(started).getTime();
  const end = finished ? new Date(finished).getTime() : Date.now();
  const secs = Math.floor((end - start) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function RunStatusIcon({ status }: { status: WorkflowRunStatus }) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />;
    case "failed":
      return <XCircle className="size-4 shrink-0 text-red-500" />;
    case "cancelled":
      return <Ban className="size-4 shrink-0 text-slate-400" />;
    case "running":
    case "pending":
      return <Loader2 className="size-4 shrink-0 animate-spin text-teal-500" />;
  }
}

function StepStatusBadge({ status }: { status: DerivedStepStatus }) {
  const colors: Record<DerivedStepStatus, string> = {
    success: "bg-emerald-100 text-emerald-700",
    partial: "bg-amber-100 text-amber-800",
    failed: "bg-red-100 text-red-700",
    running: "bg-teal-100 text-teal-700",
    pending: "bg-slate-100 text-slate-500",
    skipped: "bg-amber-100 text-amber-600",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium capitalize ${colors[status]}`}>
      {status}
    </span>
  );
}

function StepLogsModal({
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
              <StepStatusBadge
                status={deriveStepDisplayStatus(step.status, step.output)}
              />
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

function FanOutBanner({ info }: { info: FanOutInfo }) {
  const modePart =
    info.mode === "chunked" ? `chunks of ${info.chunkSize}` : "per device";
  const concurrencyPart =
    info.maxConcurrency > 0 ? ` · max ${info.maxConcurrency} concurrent` : "";
  return (
    <div className="flex items-center gap-2 border-t bg-teal-50 px-4 py-2 text-xs text-teal-900">
      <Split className="size-3.5 shrink-0 text-teal-600" aria-hidden />
      <span className="font-semibold">Fan-out run</span>
      <span className="text-teal-700">
        {info.childCount} child{info.childCount !== 1 ? "ren" : ""} ·{" "}
        {info.deviceCount} device{info.deviceCount !== 1 ? "s" : ""} · {modePart}
        {concurrencyPart}
      </span>
    </div>
  );
}

interface StepResultRowProps {
  step: WorkflowStepResult;
  runId: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenModal: () => void;
  onFocusCanvas?: (nodeId: string) => void;
  isFanOutRun?: boolean;
}

function StepResultRow({
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
            : step.step_type === "workflow-log"
            ? summarizeWorkflowLogMessage(step.output)
            : step.step_type === "show-attributes"
              ? summarizeShowAttributes(step.output)
            : null;

  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              className="text-sm font-medium truncate text-left hover:underline"
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
          <p className="text-xs text-muted-foreground font-mono">{step.step_type}</p>
          <p className="text-[11px] text-muted-foreground font-mono">
            {step.step_node_id}
          </p>
          {runHint ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground">{runHint}</p>
          ) : null}
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
            <p className="mt-0.5 text-xs text-red-500 line-clamp-1">{step.error_message}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button type="button" onClick={onToggle} className="flex items-center gap-2">
            <StepStatusBadge status={displayStatus} />
            <span className="text-xs text-muted-foreground tabular-nums">
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
          <StepResultViewer
            output={step.output}
            errorMessage={step.error_message}
            compact
            runId={runId}
          />
        </div>
      ) : null}
    </div>
  );
}

function RunDetail({
  runId,
  onFocusCanvas,
}: {
  runId: number;
  onFocusCanvas?: (nodeId: string) => void;
}) {
  const { apiCall } = useApi();

  const [logsStep, setLogsStep] = useState<WorkflowStepResult | null>(null);
  const [expandedStepId, setExpandedStepId] = useState<number | null>(null);

  const { data, isLoading } = useQuery<WorkflowRunDetail>({
    queryKey: queryKeys.workflowRuns.detail(runId),
    queryFn: () => apiCall(`runs/${runId}`, { method: "GET" }),
    staleTime: 0,
    refetchInterval: (query) => {
      const d = query.state.data as WorkflowRunDetail | undefined;
      if (!d) return 2000;
      return d.status === "pending" || d.status === "running" ? 2000 : false;
    },
  });

  const fanOutInfo = useMemo(
    () => (data ? detectRunFanOut(data.step_results) : null),
    [data],
  );

  const toggleStep = useCallback((stepId: number) => {
    setExpandedStepId((current) => (current === stepId ? null : stepId));
  }, []);

  if (isLoading || !data) {
    return (
      <div className="border-t px-4 py-3">
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (data.step_results.length === 0) {
    return (
      <div className="border-t px-4 py-3 text-xs text-muted-foreground">
        No step results yet.
      </div>
    );
  }

  return (
    <>
      {fanOutInfo ? <FanOutBanner info={fanOutInfo} /> : null}
      <div className="border-t divide-y">
        {data.step_results.map((step) => (
          <StepResultRow
            key={step.id}
            step={step}
            runId={runId}
            expanded={expandedStepId === step.id}
            onToggle={() => toggleStep(step.id)}
            onOpenModal={() => setLogsStep(step)}
            onFocusCanvas={onFocusCanvas}
            isFanOutRun={fanOutInfo !== null}
          />
        ))}
      </div>
      <StepLogsModal step={logsStep} runId={runId} onClose={() => setLogsStep(null)} />
    </>
  );
}

function RunRow({
  run,
  workflowId,
  onFocusCanvas,
}: {
  run: WorkflowRunSummary;
  workflowId: number;
  onFocusCanvas?: (nodeId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const cancelRun = useCancelRunMutation(workflowId);
  const canCancel = run.status === "pending" || run.status === "running";

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <div className="flex items-center">
        <button
          type="button"
          className="flex flex-1 min-w-0 items-center gap-3 p-4 text-left hover:bg-muted/30 transition-colors"
          onClick={() => setExpanded((v) => !v)}
        >
          <RunStatusIcon status={run.status} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">
              Run #{run.id}
              <span className="ml-2 text-xs text-muted-foreground font-normal">
                {run.uuid.slice(0, 8)}…
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              {run.triggered_by_username ?? "unknown"} · {formatTime(run.created_at)}
            </p>
          </div>
          <span className="text-xs text-muted-foreground tabular-nums mr-1">
            {formatDuration(run.started_at, run.finished_at)}
          </span>
          {expanded ? (
            <ChevronDown className="size-4 text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight className="size-4 text-muted-foreground shrink-0" />
          )}
        </button>
        {canCancel && (
          <div className="pr-3">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              disabled={cancelRun.isPending}
              onClick={() => cancelRun.mutate(run.id)}
              title="Cancel run"
            >
              <Ban className="size-3.5" />
            </Button>
          </div>
        )}
      </div>

      {expanded ? <RunDetail runId={run.id} onFocusCanvas={onFocusCanvas} /> : null}
    </div>
  );
}

interface WorkflowExecutionsPanelProps {
  onFocusNodeOnCanvas?: (nodeId: string) => void;
}

export function WorkflowExecutionsPanel({
  onFocusNodeOnCanvas,
}: WorkflowExecutionsPanelProps) {
  const workflowId = useWorkflowBuilderStore((state) => state.workflowId);
  const [filters, setFilters] = useState<WorkflowRunListFilters>(EMPTY_WORKFLOW_RUN_FILTERS);
  const handleFiltersChange = useCallback((next: WorkflowRunListFilters) => {
    setFilters(next);
  }, []);

  const { data, isLoading, isFetching } = useWorkflowRunsQuery(workflowId, { filters });

  const runs = data?.runs ?? [];
  const filtersActive = hasActiveWorkflowRunFilters(filters);

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <div className="flex items-center justify-between border-b bg-background px-6 py-4">
        <div>
          <p className="text-sm font-semibold">Executions</p>
          <p className="text-xs text-muted-foreground">
            {data ? `${data.total} run${data.total !== 1 ? "s" : ""}` : "Loading…"}
            {filtersActive ? " (filtered)" : ""}
          </p>
        </div>
        {(isLoading || isFetching) && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        )}
      </div>

      {workflowId ? (
        <WorkflowRunFiltersBar filters={filters} onChange={handleFiltersChange} />
      ) : null}

      <div className="flex-1 overflow-y-auto p-6">
        {!workflowId ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-muted-foreground">
              <Play className="mx-auto mb-2 size-8 opacity-30" />
              <p className="text-sm">Save the workflow first, then click Run.</p>
            </div>
          </div>
        ) : isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : runs.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-muted-foreground">
              <Play className="mx-auto mb-2 size-8 opacity-30" />
              <p className="text-sm">
                {filtersActive
                  ? "No runs match the current filters."
                  : "No runs yet — click Run to start the workflow."}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {runs.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                workflowId={workflowId}
                onFocusCanvas={onFocusNodeOnCanvas}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
