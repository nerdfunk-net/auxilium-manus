"use client";

import { AlertCircle, CheckCircle2, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type HatchetStatusData,
  useHatchetSettingsMutations,
} from "@/hooks/queries/use-hatchet-settings-mutations";
import { useHatchetSettingsQuery } from "@/hooks/queries/use-hatchet-settings-query";

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
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
            Hatchet is configured entirely via <code>HATCHET_CLIENT_*</code> and{" "}
            <code>HATCHET_WORKER_*</code> environment variables (in{" "}
            <code>backend/.env</code> or your docker environment) — this page is
            read-only and reflects the values the backend process actually resolved
            at startup. Changing an env var requires restarting the backend and the
            Hatchet worker process.
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
                <InfoRow label="Worker Name" value={data.worker_name} />
                <InfoRow label="Worker Slots" value={data.worker_slots} />
                <InfoRow label="SDK Version" value={data.sdk_version} />
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
