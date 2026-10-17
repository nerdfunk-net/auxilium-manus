import type { DerivedStepStatus } from "../utils/step-result-status";

const COLORS: Record<DerivedStepStatus, string> = {
  success: "bg-success text-success-foreground",
  partial: "bg-warning text-warning-foreground",
  failed: "bg-error text-error-foreground",
  running: "bg-step-surface text-step-muted-foreground",
  pending: "bg-muted text-muted-foreground",
  skipped: "bg-warning text-warning-foreground",
};

export function StepStatusBadge({ status }: { status: DerivedStepStatus }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium capitalize ${COLORS[status]}`}>
      {status}
    </span>
  );
}
