import type { DerivedStepStatus } from "../utils/step-result-status";

const COLORS: Record<DerivedStepStatus, string> = {
  success: "bg-emerald-100 text-emerald-700",
  partial: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  running: "bg-teal-100 text-teal-700",
  pending: "bg-slate-100 text-slate-500",
  skipped: "bg-amber-100 text-amber-600",
};

export function StepStatusBadge({ status }: { status: DerivedStepStatus }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium capitalize ${COLORS[status]}`}>
      {status}
    </span>
  );
}
