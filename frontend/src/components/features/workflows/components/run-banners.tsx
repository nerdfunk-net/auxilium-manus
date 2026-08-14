"use client";

import { Pause, Split } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useApproveAllMutation, useApproveBatchMutation } from "@/hooks/queries/use-workflow-run-mutations";
import type { FanOutInfo } from "../utils/step-result-status";
import type { ApprovalState } from "../types/workflow-runs";

export function FanOutBanner({ info }: { info: FanOutInfo }) {
  const modePart = info.mode === "chunked" ? `chunks of ${info.chunkSize}` : "per device";
  const concurrencyPart = info.maxConcurrency > 0 ? ` · max ${info.maxConcurrency} concurrent` : "";
  return (
    <div className="flex items-center gap-2 border-t bg-step-surface px-4 py-2 text-xs text-step-surface-foreground">
      <Split className="size-3.5 shrink-0 text-step-hover" aria-hidden />
      <span className="font-semibold">Fan-out run</span>
      <span className="text-step-muted-foreground">
        {info.childCount} child{info.childCount !== 1 ? "ren" : ""} · {info.deviceCount} device
        {info.deviceCount !== 1 ? "s" : ""} · {modePart}
        {concurrencyPart}
      </span>
    </div>
  );
}

export function ApprovalBanner({
  approvalState,
  runId,
  workflowId,
}: {
  approvalState: ApprovalState;
  runId: number;
  workflowId: number | null;
}) {
  const approveBatch = useApproveBatchMutation(workflowId);
  const approveAll = useApproveAllMutation(workflowId);
  const names = approvalState.next_batch_device_names;
  const preview = names.slice(0, 10).join(", ") + (names.length > 10 ? ", …" : "");

  return (
    <div className="space-y-2 border-t bg-warning px-4 py-2 text-xs text-warning-foreground">
      <div className="flex items-center gap-2">
        <Pause className="size-3.5 shrink-0 text-warning-foreground" aria-hidden />
        <span className="font-semibold">
          Waiting for approval — batch {approvalState.next_batch_index + 1}/
          {approvalState.total_batches}
        </span>
      </div>
      <p className="text-warning-foreground">
        {names.length} device{names.length !== 1 ? "s" : ""} next: {preview || "—"}
      </p>
      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          disabled={approveBatch.isPending}
          onClick={() => approveBatch.mutate(runId)}
        >
          Run next batch
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          disabled={approveAll.isPending}
          onClick={() => approveAll.mutate(runId)}
        >
          Run all remaining
        </Button>
      </div>
    </div>
  );
}
