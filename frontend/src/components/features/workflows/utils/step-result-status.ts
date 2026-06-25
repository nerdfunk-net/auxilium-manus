import { parseStepOutput } from "@/lib/workflow-context-types";

import type { StepStatus } from "../types/workflow-runs";

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
