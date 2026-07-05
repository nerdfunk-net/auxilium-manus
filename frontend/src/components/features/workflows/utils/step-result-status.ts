import { parseStepOutput } from "@/lib/workflow-context-types";

import type { StepStatus, WorkflowStepResult } from "../types/workflow-runs";

/** Display status derived from persisted step result + optional engine status. */
export type DerivedStepStatus = StepStatus | "partial";

export function deriveStepDisplayStatus(
  engineStatus: StepStatus,
  output: Record<string, unknown> | null,
): DerivedStepStatus {
  if (engineStatus === "pending" || engineStatus === "running" || engineStatus === "skipped") {
    return engineStatus;
  }
  if (engineStatus === "failed") {
    return "failed";
  }

  const envelope = parseStepOutput(output);
  if (!envelope) {
    return engineStatus;
  }

  const successContext = envelope.outcomes.success;
  const failureContext = envelope.outcomes.failure;

  const successCount = successContext ? Object.keys(successContext.devices).length : 0;
  const failureCount = failureContext ? Object.keys(failureContext.devices).length : 0;

  if (failureCount > 0 && successCount > 0) {
    return "partial";
  }
  if (failureCount > 0 && successCount === 0) {
    return "failed";
  }

  if (engineStatus === "success") {
    return "success";
  }

  return engineStatus;
}

export function countOutcomeDevices(
  output: Record<string, unknown> | null,
): { success: number; failure: number; totalOutcomes: number } {
  const envelope = parseStepOutput(output);
  if (!envelope) {
    return { success: 0, failure: 0, totalOutcomes: 0 };
  }

  const success = envelope.outcomes.success
    ? Object.keys(envelope.outcomes.success.devices).length
    : 0;
  const failure = envelope.outcomes.failure
    ? Object.keys(envelope.outcomes.failure.devices).length
    : 0;

  return {
    success,
    failure,
    totalOutcomes: Object.keys(envelope.outcomes).length,
  };
}

function firstOutcomeMetadata(
  output: Record<string, unknown> | null,
): Record<string, unknown> | null {
  const envelope = parseStepOutput(output);
  if (!envelope) {
    return null;
  }
  const firstOutcome = Object.values(envelope.outcomes)[0];
  return firstOutcome?.metadata ?? null;
}

/** Short summary for route-on-attribute results in the run list. */
export function summarizeRouteCounts(
  output: Record<string, unknown> | null,
): string | null {
  const metadata = firstOutcomeMetadata(output);
  if (!metadata) {
    return null;
  }

  const routedCounts = Object.entries(metadata).find(([key]) =>
    key.endsWith(".routed_counts"),
  )?.[1];
  if (!routedCounts || typeof routedCounts !== "object" || routedCounts === null) {
    return null;
  }

  const parts = Object.entries(routedCounts as Record<string, unknown>)
    .filter(([, count]) => typeof count === "number" && count > 0)
    .map(([outcome, count]) => `${outcome}: ${count}`);

  return parts.length > 0 ? parts.join(" · ") : "no devices routed";
}

/** Short summary for workflow-log message in the run list. */
export function summarizeWorkflowLogMessage(
  output: Record<string, unknown> | null,
): string | null {
  const metadata = firstOutcomeMetadata(output);
  if (!metadata) {
    return null;
  }

  const debugLogs = Object.entries(metadata).find(([key]) =>
    key.endsWith(".debug_logs"),
  )?.[1];
  if (!debugLogs || typeof debugLogs !== "object" || debugLogs === null) {
    return null;
  }

  const message = (debugLogs as Record<string, unknown>).message;
  return typeof message === "string" && message.trim() ? message.trim() : null;
}

/** Short summary for show-attributes destination/format in the run list. */
export function summarizeShowAttributes(
  output: Record<string, unknown> | null,
): string | null {
  const metadata = firstOutcomeMetadata(output);
  if (!metadata) {
    return null;
  }

  const payload = Object.entries(metadata).find(([key]) =>
    key.endsWith(".show_attributes"),
  )?.[1];
  if (!payload || typeof payload !== "object" || payload === null) {
    return null;
  }

  const record = payload as Record<string, unknown>;
  const destination =
    record.output_destination === "file" ? "file" : "STDOUT";
  const format = record.output_format === "pretty_text" ? "pretty text" : "JSON";
  const deviceCount =
    typeof record.device_count === "number" ? record.device_count : null;
  const parts = [`${destination} · ${format}`];
  if (deviceCount != null) {
    parts.push(`${deviceCount} device${deviceCount === 1 ? "" : "s"}`);
  }
  if (record.output_destination === "file" && typeof record.file_path === "string") {
    parts.push(record.file_path);
  }
  return parts.join(" · ");
}

const INVENTORY_STEP_TYPES = new Set(["get-nautobot-devices", "get-git-devices"]);

export interface FanOutInfo {
  mode: "per_device" | "chunked";
  chunkSize: number;
  maxConcurrency: number;
  deviceCount: number;
  childCount: number;
}

function extractFanOutFromOutput(
  output: Record<string, unknown> | null,
): FanOutInfo | null {
  const envelope = parseStepOutput(output);
  if (!envelope) return null;
  const firstOutcome = Object.values(envelope.outcomes)[0];
  if (!firstOutcome) return null;
  const fanOut = firstOutcome.metadata._fan_out;
  if (!fanOut || typeof fanOut !== "object" || !(fanOut as Record<string, unknown>).enabled) {
    return null;
  }
  const fo = fanOut as Record<string, unknown>;
  const mode = fo.mode === "chunked" ? "chunked" : "per_device";
  const chunkSize = Math.max(1, typeof fo.chunk_size === "number" ? fo.chunk_size : 1);
  const maxConcurrency = typeof fo.max_concurrency === "number" ? fo.max_concurrency : 0;
  const deviceCount = Object.keys(firstOutcome.devices).length;
  const childCount = mode === "chunked" ? Math.ceil(deviceCount / chunkSize) : deviceCount;
  return { mode, chunkSize, maxConcurrency, deviceCount, childCount };
}

/** Scan step results to find whether this run used fan-out and extract its config. */
export function detectRunFanOut(stepResults: WorkflowStepResult[]): FanOutInfo | null {
  for (const step of stepResults) {
    if (!INVENTORY_STEP_TYPES.has(step.step_type)) continue;
    const info = extractFanOutFromOutput(step.output);
    if (info) return info;
  }
  return null;
}

/** Short hint for inventory steps showing their fan-out config. */
export function summarizeFanOutInventory(
  output: Record<string, unknown> | null,
): string | null {
  const info = extractFanOutFromOutput(output);
  if (!info) return null;
  const modePart =
    info.mode === "chunked" ? `chunked (${info.chunkSize}/child)` : "per device";
  const concurrencyPart =
    info.maxConcurrency > 0 ? ` · max ${info.maxConcurrency} concurrent` : "";
  return `Fan-out: ${info.childCount} child${info.childCount !== 1 ? "ren" : ""} · ${modePart}${concurrencyPart}`;
}

/** Short hint for fan-in steps showing how many devices were merged. */
export function summarizeFanIn(
  output: Record<string, unknown> | null,
): string | null {
  const envelope = parseStepOutput(output);
  if (!envelope) return null;
  const firstOutcome = Object.values(envelope.outcomes)[0];
  if (!firstOutcome) return null;
  const fanInEntry = Object.entries(firstOutcome.metadata).find(([key]) =>
    key.endsWith(".fan_in"),
  );
  if (!fanInEntry) return null;
  const value = fanInEntry[1];
  if (typeof value !== "object" || value === null) return null;
  const deviceCount = (value as Record<string, unknown>).device_count;
  if (typeof deviceCount !== "number") return null;
  return `Merged ${deviceCount} device${deviceCount !== 1 ? "s" : ""} from fan-out children`;
}

/** Short summary for render-jinja-template results in the run list. */
export function summarizeRenderJinjaTemplate(
  output: Record<string, unknown> | null,
): string | null {
  const metadata = firstOutcomeMetadata(output);
  if (!metadata) {
    return null;
  }

  const successEntry = Object.entries(metadata).find(([key]) =>
    key.endsWith(".rendered_success_count"),
  );
  if (!successEntry) {
    return null;
  }

  const nodePrefix = successEntry[0].slice(0, -".rendered_success_count".length);
  const successCount = successEntry[1];
  const failureCount = metadata[`${nodePrefix}.rendered_failure_count`];
  const outputKey = metadata[`${nodePrefix}.rendered_template_key`];

  if (typeof successCount !== "number") {
    return null;
  }

  const failurePart =
    typeof failureCount === "number" && failureCount > 0 ? ` · ${failureCount} failed` : "";
  const keyPart = typeof outputKey === "string" && outputKey ? ` → ${outputKey}` : "";

  return `${successCount} rendered${failurePart}${keyPart}`;
}

/** Short summary for compare-data results in the run list. */
export function summarizeCompareData(
  output: Record<string, unknown> | null,
): string | null {
  const metadata = firstOutcomeMetadata(output);
  if (!metadata) {
    return null;
  }

  const countsEntry = Object.entries(metadata).find(([key]) =>
    key.endsWith(".comparison_counts"),
  );
  if (!countsEntry) {
    return null;
  }

  const counts = countsEntry[1];
  if (typeof counts !== "object" || counts === null) {
    return null;
  }

  const match = (counts as Record<string, unknown>).match;
  const mismatch = (counts as Record<string, unknown>).mismatch;
  const failure = (counts as Record<string, unknown>).failure;

  const parts: string[] = [];
  if (typeof match === "number" && match > 0) {
    parts.push(`${match} match`);
  }
  if (typeof mismatch === "number" && mismatch > 0) {
    parts.push(`${mismatch} mismatch`);
  }
  if (typeof failure === "number" && failure > 0) {
    parts.push(`${failure} failed`);
  }

  return parts.length > 0 ? parts.join(" · ") : "no devices compared";
}
