import { CheckCircle2, CircleDashed, Timer } from "lucide-react";

const mockExecutions = [
  {
    id: "run-001",
    title: "Manual backup test",
    status: "Success",
    timestamp: "Not persisted yet",
  },
  {
    id: "run-002",
    title: "Draft validation",
    status: "Queued",
    timestamp: "Mock data",
  },
];

export function WorkflowExecutionsPanel() {
  return (
    <div className="flex h-full items-center justify-center bg-slate-50 p-10">
      <div className="w-full max-w-3xl rounded-2xl border bg-card p-6 shadow-sm">
        <div className="mb-6">
          <p className="text-sm font-semibold">Executions</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Real Hatchet-backed runs will appear here after backend integration.
          </p>
        </div>
        <div className="space-y-3">
          {mockExecutions.map((execution) => (
            <div
              key={execution.id}
              className="flex items-center justify-between rounded-xl border p-4"
            >
              <div className="flex items-center gap-3">
                {execution.status === "Success" ? (
                  <CheckCircle2 className="size-5 text-emerald-600" />
                ) : (
                  <CircleDashed className="size-5 text-amber-600" />
                )}
                <div>
                  <p className="text-sm font-medium">{execution.title}</p>
                  <p className="text-xs text-muted-foreground">{execution.id}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Timer className="size-4" />
                {execution.timestamp}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
