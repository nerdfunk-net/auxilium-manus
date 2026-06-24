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
