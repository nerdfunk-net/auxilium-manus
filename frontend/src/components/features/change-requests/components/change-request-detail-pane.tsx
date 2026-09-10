"use client";

import { useMemo, useState } from "react";
import { GitBranch, Loader2, Rocket } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useWorkflowsQuery } from "@/hooks/queries/use-workflows-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { useChangeRequestDiffQuery } from "../hooks/use-change-request-diff-query";
import { useChangeRequestMutations } from "../hooks/use-change-request-mutations";
import { useChangeRequestQuery } from "../hooks/use-change-request-query";
import { ChangeRequestStatusBadge } from "./change-request-status-badge";
import { UnifiedDiffView } from "./unified-diff-view";

function formatTimestamp(iso: string | null): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : "—";
}

interface ChangeRequestDetailPaneProps {
  changeRequestId: number | null;
}

export function ChangeRequestDetailPane({ changeRequestId }: ChangeRequestDetailPaneProps) {
  const user = useAuthStore((state) => state.user);
  const canApprove = hasPermission(user, "change_requests", "approve");

  const { data, isLoading } = useChangeRequestQuery(changeRequestId);
  const diffQuery = useChangeRequestDiffQuery(changeRequestId, {
    enabled: data?.diff_artifact_id != null,
  });
  const { approve, deploy, reject } = useChangeRequestMutations();
  const { data: workflowsData } = useWorkflowsQuery();

  // This component is remounted (via key) when the selected change request
  // changes, so local dialog state starts fresh — no reset effect needed.
  const [actionMode, setActionMode] = useState<"approve" | "deploy" | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [selectedDeployWorkflowId, setSelectedDeployWorkflowId] = useState<string>("");

  const needsWorkflowChoice = data?.deploy_workflow_id == null;
  const deployWorkflowId = useMemo(() => {
    if (!needsWorkflowChoice) return data?.deploy_workflow_id ?? null;
    return selectedDeployWorkflowId ? Number(selectedDeployWorkflowId) : null;
  }, [needsWorkflowChoice, data?.deploy_workflow_id, selectedDeployWorkflowId]);

  if (changeRequestId == null) {
    return (
      <div className="flex h-full items-center justify-center text-center text-muted-foreground">
        <div>
          <GitBranch className="mx-auto mb-2 size-8 opacity-30" />
          <p className="text-sm">Select a change request to review it.</p>
        </div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const isPending = approve.isPending || deploy.isPending;
  const canAct = canApprove && (data.status === "staged" || data.status === "approved");
  const primaryLabel = data.status === "staged" ? "Approve & Deploy" : "Deploy";

  const runAction = () => {
    if (!changeRequestId) return;
    const variables = { id: changeRequestId, deployWorkflowId };
    const mutation = data.status === "staged" ? approve : deploy;
    mutation.mutate(variables, { onSuccess: () => setActionMode(null) });
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="space-y-4 border-b px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-foreground">
              {data.title || `Change request #${data.id}`}
            </h2>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono">#{data.id}</span>
              {data.branch ? (
                <span className="inline-flex items-center gap-1 font-mono">
                  <GitBranch className="size-3" aria-hidden />
                  {data.branch}
                </span>
              ) : null}
              {data.commit_sha ? (
                <span className="font-mono">{data.commit_sha.slice(0, 10)}</span>
              ) : null}
            </p>
          </div>
          <ChangeRequestStatusBadge status={data.status} />
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <div>
            <dt className="text-muted-foreground">Stage run</dt>
            <dd className="font-mono">{data.source_run_id ? `#${data.source_run_id}` : "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Deploy run</dt>
            <dd className="font-mono">{data.deploy_run_id ? `#${data.deploy_run_id}` : "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Devices</dt>
            <dd>{data.device_ids.length}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Created</dt>
            <dd>{formatTimestamp(data.created_at)}</dd>
          </div>
          {data.status === "staged" && data.expires_at ? (
            <div>
              <dt className="text-muted-foreground">Expires</dt>
              <dd>{formatTimestamp(data.expires_at)}</dd>
            </div>
          ) : null}
          {data.approved_at ? (
            <div>
              <dt className="text-muted-foreground">Reviewed</dt>
              <dd>
                {formatTimestamp(data.approved_at)}
                {data.approved_via ? ` (${data.approved_via})` : ""}
              </dd>
            </div>
          ) : null}
        </dl>

        {data.status === "failed" && data.deploy_error ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {data.deploy_error}
          </p>
        ) : null}
        {data.status === "rejected" && data.reject_reason ? (
          <p className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
            Rejected: {data.reject_reason}
          </p>
        ) : null}

        {canAct ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={isPending}
              onClick={() => setActionMode(data.status === "staged" ? "approve" : "deploy")}
            >
              <Rocket className="size-4" aria-hidden />
              {primaryLabel}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={reject.isPending}
              onClick={() => setRejecting(true)}
            >
              Reject
            </Button>
          </div>
        ) : null}
      </div>

      <div className="flex-1 space-y-2 px-5 py-4">
        <p className="text-xs font-medium text-muted-foreground">Rendered config diff</p>
        {data.diff_artifact_id == null ? (
          <p className="text-sm text-muted-foreground">No diff was stored for this change.</p>
        ) : diffQuery.isLoading ? (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        ) : diffQuery.error ? (
          <p className="text-sm text-destructive">Could not load the diff.</p>
        ) : diffQuery.data ? (
          <UnifiedDiffView
            diff={diffQuery.data.content}
            truncated={data.diff_stats?.truncated}
          />
        ) : null}
      </div>

      <Dialog open={actionMode != null} onOpenChange={(next) => !next && setActionMode(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{primaryLabel}?</DialogTitle>
            <DialogDescription>
              This queues a deploy run that applies the staged config to{" "}
              {data.device_ids.length} device{data.device_ids.length === 1 ? "" : "s"}.
            </DialogDescription>
          </DialogHeader>
          {needsWorkflowChoice ? (
            <div className="space-y-2">
              <Label htmlFor="cr-deploy-workflow">Deploy workflow</Label>
              <Select
                value={selectedDeployWorkflowId}
                onValueChange={setSelectedDeployWorkflowId}
              >
                <SelectTrigger id="cr-deploy-workflow">
                  <SelectValue placeholder="Select a workflow" />
                </SelectTrigger>
                <SelectContent>
                  {(workflowsData?.workflows ?? []).map((workflow) => (
                    <SelectItem key={workflow.id} value={String(workflow.id)}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setActionMode(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={isPending || (needsWorkflowChoice && !selectedDeployWorkflowId)}
              onClick={runAction}
            >
              {isPending ? "Queuing…" : primaryLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejecting} onOpenChange={(next) => !next && setRejecting(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Reject change request?</DialogTitle>
            <DialogDescription>
              The staged branch stays in git but the change will not be deployed.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cr-reject-reason">Reason (optional)</Label>
            <Textarea
              id="cr-reject-reason"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={reject.isPending}
              onClick={() =>
                changeRequestId != null &&
                reject.mutate(
                  { id: changeRequestId, reason: rejectReason.trim() || undefined },
                  { onSuccess: () => setRejecting(false) },
                )
              }
            >
              {reject.isPending ? "Rejecting…" : "Reject"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
