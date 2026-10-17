"use client";

import { AlertCircle, CheckCircle2, ExternalLink, HelpCircle, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  type HatchetStatusData,
  useHatchetSettingsMutations,
} from "@/hooks/queries/use-hatchet-settings-mutations";
import { useHatchetSettingsQuery } from "@/hooks/queries/use-hatchet-settings-query";

function InfoRow({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5 text-sm">
      <span className="flex items-center gap-1.5 text-muted-foreground">
        {label}
        {hint && (
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle className="size-3.5 cursor-help" />
            </TooltipTrigger>
            <TooltipContent side="top">{hint}</TooltipContent>
          </Tooltip>
        )}
      </span>
      <span className="min-w-0 truncate font-mono text-[13px]">{value}</span>
    </div>
  );
}

export function HatchetSettingsCanvas() {
  const { data, isLoading } = useHatchetSettingsQuery();
  const { testConnection } = useHatchetSettingsMutations();
  const [lastStatus, setLastStatus] = useState<HatchetStatusData | null>(null);

  const handleTest = async () => {
    const result = await testConnection.mutateAsync();
    setLastStatus(result);
  };

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <div className="flex items-start gap-2 rounded-md bg-warning px-3 py-2 text-xs text-warning-foreground">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <p>
            Hatchet is configured entirely via <code>HATCHET_CLIENT_*</code>,{" "}
            <code>HATCHET_WORKER_*</code>, and <code>HATCHET_DYNAMIC_WORKER_*</code>{" "}
            environment variables (in <code>backend/.env</code> or your docker
            environment) — this page is read-only and reflects the values this
            backend (API) process resolved for itself and for both worker
            processes at its own startup, not a live check of either worker.
            Changing an env var requires restarting the backend and the
            corresponding Hatchet worker process.
          </p>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Connection Status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {lastStatus ? (
              <div className="flex items-start gap-3">
                {lastStatus.reachable ? (
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success-foreground" />
                ) : (
                  <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={lastStatus.reachable ? "default" : "destructive"}
                      className={lastStatus.reachable ? "bg-success-foreground hover:bg-success-foreground" : ""}
                    >
                      {lastStatus.reachable ? "Connected" : "Unreachable"}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {new Date(lastStatus.checked_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{lastStatus.message}</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {isLoading
                  ? "Loading configuration…"
                  : "Run a connection test to check the Hatchet engine status."}
              </p>
            )}

            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={testConnection.isPending}
                onClick={handleTest}
              >
                {testConnection.isPending ? (
                  <Loader2 className="mr-2 size-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 size-4" />
                )}
                Test Connection
              </Button>
              {data?.dashboard_url && (
                <Button type="button" variant="outline" size="sm" asChild>
                  <a href={data.dashboard_url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="mr-2 size-4" />
                    Open Dashboard
                  </a>
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Resolved Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading || !data ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <div className="divide-y">
                <InfoRow label="Server URL (REST)" value={data.server_url} />
                <InfoRow label="Dashboard URL (browser)" value={data.dashboard_url} />
                <InfoRow label="Host:Port (gRPC)" value={data.host_port} />
                <InfoRow label="Tenant ID" value={data.tenant_id || "—"} />
                <InfoRow label="Namespace" value={data.namespace || "—"} />
                <InfoRow label="TLS Strategy" value={data.tls_strategy} />
                <InfoRow label="Debug Mode" value={data.debug ? "Enabled" : "Disabled"} />
                <InfoRow
                  label="Token"
                  value={
                    data.token_configured ? (
                      <span className="text-success-foreground">Configured</span>
                    ) : (
                      <span className="text-warning-foreground">Not set</span>
                    )
                  }
                />
                <InfoRow
                  label="Live Worker Name"
                  value={data.worker_name}
                  hint="Identifies the live worker process to Hatchet (HATCHET_WORKER_NAME). Handles every unpublished workflow — the default for all workflows."
                />
                <InfoRow
                  label="Live Worker Slots"
                  value={data.worker_slots}
                  hint="How many Hatchet tasks the live worker process runs concurrently, across every workflow type it handles — top-level workflow runs, fan-out device-group children, cache-devices, scheduled triggers, and retention purges all draw from this same pool. It is not the per-step fan-out chunk size (set per-node in the canvas) and is not scoped to a single run — other workflow activity on this worker competes for the same slots."
                />
                <InfoRow
                  label="Background Worker Name"
                  value={data.dynamic_worker_name}
                  hint="Identifies the second worker process to Hatchet (HATCHET_DYNAMIC_WORKER_NAME). Only handles workflows explicitly published to the background tier — see the Properties panel's 'Publish to background tier' toggle."
                />
                <InfoRow
                  label="Background Worker Slots"
                  value={data.dynamic_worker_slots}
                  hint="Concurrency cap for the background worker process — independent of Live Worker Slots above; a published workflow's throughput is governed by this pool, not the live worker's."
                />
                <InfoRow
                  label="Background Worker Poll Interval"
                  value={`${data.dynamic_worker_poll_interval_seconds}s`}
                  hint="How often the background worker checks for a newly published, edited, or unpublished workflow and restarts itself to pick it up (HATCHET_DYNAMIC_WORKER_POLL_INTERVAL_SECONDS)."
                />
                <InfoRow label="SDK Version" value={data.sdk_version} />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Worker Slots vs. Fan-Out Batching</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">Worker Slots</span> is a
              global concurrency cap on this worker process: the maximum number of
              Hatchet tasks it will execute at once, shared across{" "}
              <em>all</em> workflow runs and workflow types currently in flight —
              not just one workflow&apos;s fan-out.
            </p>
            <p>
              A workflow step&apos;s{" "}
              <span className="font-medium text-foreground">fan-out</span> settings
              (mode, chunk size, max concurrency) are configured independently, per
              inventory node, in the canvas — they default to fan-out disabled and
              are unrelated to this env var.
            </p>
            <p>
              When fan-out dispatches more concurrent device groups than there are
              free worker slots, the extra ones queue in Hatchet and start as slots
              free up — a rolling pool, not a &quot;wait for the whole batch to
              finish&quot; boundary. Raising Worker Slots increases how much a
              single worker process can run in parallel overall; it does not change
              how any one workflow groups its devices.
            </p>
            <p>
              A workflow published to the background tier runs on the{" "}
              <span className="font-medium text-foreground">background worker</span>,
              with its own independent Worker Slots pool and, optionally, its own
              Hatchet-native concurrency limit set at publish time (capping
              overlapping <em>runs</em> of that one workflow, not devices within a
              run). See{" "}
              <code>doc/HOWTO_BUILD_WORKFLOWS.md</code> for how that combines with
              fan-out.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
