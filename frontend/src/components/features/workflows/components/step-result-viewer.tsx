"use client";

import { AlertCircle, CheckCircle2, FileJson, Server, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Capability } from "@/lib/capability-types";
import type {
  ArtifactRef,
  DeviceContext,
  DeviceError,
  WorkflowContext,
} from "@/lib/workflow-context-types";
import { parseStepOutput } from "@/lib/workflow-context-types";

interface StepResultViewerProps {
  output: Record<string, unknown> | null;
  errorMessage?: string | null;
  compact?: boolean;
}

function DeviceStatusIcon({ status }: { status: DeviceContext["status"] }) {
  switch (status) {
    case "ok":
      return <CheckCircle2 className="size-3.5 text-emerald-600" />;
    case "failed":
      return <XCircle className="size-3.5 text-red-500" />;
    default:
      return <AlertCircle className="size-3.5 text-muted-foreground" />;
  }
}

function CapabilityBadges({ capabilities }: { capabilities: Capability[] }) {
  if (capabilities.length === 0) {
    return <span className="text-xs text-muted-foreground">none</span>;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {capabilities.map((cap) => (
        <Badge key={cap} className="font-mono text-[10px]" variant="secondary">
          {cap}
        </Badge>
      ))}
    </div>
  );
}

function ArtifactRefRow({ label, artifactRef }: { label: string; artifactRef: ArtifactRef }) {
  return (
    <div className="rounded border bg-background/60 px-2 py-1.5 text-xs">
      <p className="font-medium text-muted-foreground">{label}</p>
      <p className="font-mono">{artifactRef.artifact_id}</p>
      <p className="text-muted-foreground">
        {artifactRef.kind}
        {artifactRef.size_bytes != null ? ` · ${artifactRef.size_bytes} bytes` : ""}
      </p>
    </div>
  );
}

function DeviceErrorList({ errors }: { errors: DeviceError[] }) {
  if (errors.length === 0) {
    return null;
  }

  return (
    <ul className="mt-2 space-y-1">
      {errors.map((error, index) => (
        <li
          key={`${error.code}-${error.occurred_at}-${index}`}
          className="rounded bg-red-50 px-2 py-1 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-400"
        >
          <span className="font-mono font-medium">{error.code}</span>
          {" — "}
          {error.message}
        </li>
      ))}
    </ul>
  );
}

function DeviceCard({ device }: { device: DeviceContext }) {
  const [showAttributes, setShowAttributes] = useState(false);
  const attributeKeys = Object.keys(device.attributes);

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-start gap-2">
        <DeviceStatusIcon status={device.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{device.name}</p>
            <Badge className="font-mono text-[10px]" variant="outline">
              {device.status}
            </Badge>
            {device.source ? (
              <Badge className="text-[10px]" variant="secondary">
                {device.source}
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">{device.id}</p>
          <p className="text-xs text-muted-foreground">
            {device.hostname}
            {device.primary_ip4 ? ` · ${device.primary_ip4}` : ""}
            {device.network_driver ? ` · ${device.network_driver}` : ""}
          </p>
          <div className="mt-2">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Capabilities
            </p>
            <CapabilityBadges capabilities={device.capabilities} />
          </div>
          {device.running_config_ref || device.startup_config_ref ? (
            <div className="mt-2 space-y-1">
              {device.running_config_ref ? (
                <ArtifactRefRow
                  label="Running config"
                  artifactRef={device.running_config_ref}
                />
              ) : null}
              {device.startup_config_ref ? (
                <ArtifactRefRow
                  label="Startup config"
                  artifactRef={device.startup_config_ref}
                />
              ) : null}
            </div>
          ) : null}
          <DeviceErrorList errors={device.errors} />
          {attributeKeys.length > 0 ? (
            <div className="mt-2">
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={() => setShowAttributes((value) => !value)}
              >
                {showAttributes ? "Hide" : "Show"} attributes ({attributeKeys.length})
              </button>
              {showAttributes ? (
                <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted/40 p-2 text-[11px] font-mono">
                  {JSON.stringify(device.attributes, null, 2)}
                </pre>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function MetadataPanel({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata);
  if (entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No step metadata recorded.</p>
    );
  }

  return (
    <div className="space-y-1">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="flex items-start justify-between gap-3 rounded border bg-background/60 px-2 py-1.5 text-xs"
        >
          <span className="font-mono text-muted-foreground">{key}</span>
          <span className="max-w-[60%] truncate font-mono text-right">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function OutcomeContextView({ context }: { context: WorkflowContext }) {
  const devices = Object.values(context.devices);
  const pendingCommandNodes = Object.keys(context.pending_commands);

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <Server className="size-3.5" />
          Devices ({devices.length})
        </p>
        {devices.length === 0 ? (
          <p className="text-xs text-muted-foreground">No devices on this outcome path.</p>
        ) : (
          <div className="space-y-2">
            {devices.map((device) => (
              <DeviceCard key={device.id} device={device} />
            ))}
          </div>
        )}
      </div>

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Metadata
        </p>
        <MetadataPanel metadata={context.metadata} />
      </div>

      {pendingCommandNodes.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Pending commands
          </p>
          <pre className="max-h-32 overflow-auto rounded bg-muted/40 p-2 text-[11px] font-mono">
            {JSON.stringify(context.pending_commands, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

export function StepResultViewer({
  output,
  errorMessage,
  compact = false,
}: StepResultViewerProps) {
  const envelope = useMemo(() => parseStepOutput(output), [output]);
  const outcomeNames = useMemo(
    () => (envelope ? Object.keys(envelope.outcomes) : []),
    [envelope],
  );
  const [selectedOutcome, setSelectedOutcome] = useState<string | null>(null);
  const activeOutcome = useMemo(() => {
    if (selectedOutcome && outcomeNames.includes(selectedOutcome)) {
      return selectedOutcome;
    }
    return outcomeNames[0] ?? "success";
  }, [outcomeNames, selectedOutcome]);

  if (errorMessage) {
    return (
      <pre className="max-h-48 overflow-auto rounded bg-red-50 p-3 text-xs font-mono text-red-700 dark:bg-red-950/30 dark:text-red-400">
        {errorMessage}
      </pre>
    );
  }

  if (!envelope) {
    if (!output) {
      return (
        <p className="text-xs text-muted-foreground">No output recorded for this step.</p>
      );
    }

    return (
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs text-amber-600">
          <FileJson className="size-3.5" />
          Legacy or unstructured output
        </p>
        <pre className="max-h-60 overflow-auto rounded bg-muted/30 p-3 text-xs font-mono">
          {JSON.stringify(output, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <Tabs
      value={activeOutcome}
      onValueChange={setSelectedOutcome}
      className={compact ? "w-full" : undefined}
    >
      <TabsList className="h-8 flex-wrap">
        {outcomeNames.map((name) => {
          const deviceCount = Object.keys(envelope.outcomes[name].devices).length;
          return (
            <TabsTrigger key={name} value={name} className="text-xs capitalize">
              {name}
              <Badge className="ml-1.5 h-4 px-1 text-[10px]" variant="secondary">
                {deviceCount}
              </Badge>
            </TabsTrigger>
          );
        })}
      </TabsList>
      {outcomeNames.map((name) => (
        <TabsContent key={name} value={name} className="mt-3">
          <OutcomeContextView context={envelope.outcomes[name]} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
