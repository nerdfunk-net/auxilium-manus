"use client";

import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, FileJson, Loader2, ScrollText, Server, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useArtifactQuery } from "@/hooks/queries/use-artifact-query";
import type { Capability } from "@/lib/capability-types";
import { cn } from "@/lib/utils";
import type {
  ArtifactRef,
  CommandResult,
  DeviceContext,
  DeviceError,
  WorkflowContext,
} from "@/lib/workflow-context-types";
import { parseStepOutput } from "@/lib/workflow-context-types";

interface StepResultViewerProps {
  output: Record<string, unknown> | null;
  errorMessage?: string | null;
  compact?: boolean;
  runId?: number | null;
}

/** Lists with more than this many devices start collapsed. */
const DEVICES_COLLAPSE_THRESHOLD = 5;
const DEBUG_LOGS_METADATA_SUFFIX = ".debug_logs";
const SHOW_ATTRIBUTES_METADATA_SUFFIX = ".show_attributes";

interface DebugLogDeviceEntry {
  device_id: string;
  device_name: string;
  values: Record<string, unknown>;
}

interface DebugLogsPayload {
  message?: string;
  logged_at?: string;
  attribute_paths?: string[];
  device_count?: number;
  devices: Record<string, DebugLogDeviceEntry>;
}

function isDebugLogsPayload(value: unknown): value is DebugLogsPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "devices" in value &&
    typeof (value as DebugLogsPayload).devices === "object"
  );
}

interface ShowAttributesPayload {
  output_destination?: string;
  output_format?: string;
  filename?: string | null;
  append?: boolean | null;
  file_path?: string | null;
  written_at?: string;
  device_count?: number;
  content?: string;
}

function isShowAttributesPayload(value: unknown): value is ShowAttributesPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    ("content" in value || "snapshot" in value)
  );
}

function extractDebugLogs(metadata: Record<string, unknown>): DebugLogsPayload[] {
  return Object.entries(metadata)
    .filter(([key]) => key.endsWith(DEBUG_LOGS_METADATA_SUFFIX))
    .map(([, value]) => value)
    .filter(isDebugLogsPayload);
}

function extractShowAttributes(metadata: Record<string, unknown>): ShowAttributesPayload[] {
  return Object.entries(metadata)
    .filter(([key]) => key.endsWith(SHOW_ATTRIBUTES_METADATA_SUFFIX))
    .map(([, value]) => value)
    .filter(isShowAttributesPayload);
}

function metadataWithoutDebugPanels(metadata: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(metadata).filter(
      ([key]) =>
        !key.endsWith(DEBUG_LOGS_METADATA_SUFFIX) &&
        !key.endsWith(SHOW_ATTRIBUTES_METADATA_SUFFIX),
    ),
  );
}

function formatLogValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function DebugLogsPanel({ logs }: { logs: DebugLogsPayload[] }) {
  if (logs.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {logs.map((entry, index) => {
        const deviceEntries = Object.values(entry.devices ?? {});
        return (
          <div key={`debug-log-${index}`} className="rounded-lg border bg-card p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <ScrollText className="size-3.5 shrink-0 text-muted-foreground" />
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Debug log
              </p>
              {entry.message ? (
                <Badge className="text-[10px]" variant="secondary">
                  {entry.message}
                </Badge>
              ) : null}
              {entry.logged_at ? (
                <span className="text-[11px] text-muted-foreground">{entry.logged_at}</span>
              ) : null}
            </div>

            {entry.attribute_paths && entry.attribute_paths.length > 0 ? (
              <p className="mb-2 text-[11px] text-muted-foreground">
                Paths:{" "}
                <span className="font-mono">{entry.attribute_paths.join(", ")}</span>
              </p>
            ) : null}

            {deviceEntries.length === 0 ? (
              <p className="text-xs text-muted-foreground">No devices were present in context.</p>
            ) : (
              <div className="space-y-2">
                {deviceEntries.map((deviceEntry) => (
                  <div
                    key={deviceEntry.device_id}
                    className="rounded border bg-background/60 p-2 text-xs"
                  >
                    <p className="font-medium">{deviceEntry.device_name}</p>
                    <p className="break-all font-mono text-[11px] text-muted-foreground">
                      {deviceEntry.device_id}
                    </p>
                    <div className="mt-2 space-y-1">
                      {Object.entries(deviceEntry.values ?? {}).map(([path, value]) => (
                        <div key={path} className="min-w-0">
                          <span className="block break-all font-mono text-[11px] text-muted-foreground">
                            {path}
                          </span>
                          <pre className="mt-0.5 max-h-32 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-1.5 font-mono text-[11px]">
                            {formatLogValue(value)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ShowAttributesPanel({ entries }: { entries: ShowAttributesPayload[] }) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {entries.map((entry, index) => (
        <div key={`show-attributes-${index}`} className="rounded-lg border bg-card p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <ScrollText className="size-3.5 shrink-0 text-muted-foreground" />
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Show attributes
            </p>
            {entry.output_destination ? (
              <Badge className="text-[10px]" variant="secondary">
                {entry.output_destination === "file" ? "file" : "STDOUT"}
              </Badge>
            ) : null}
            {entry.output_format ? (
              <Badge className="text-[10px]" variant="outline">
                {entry.output_format === "pretty_text" ? "pretty text" : "JSON"}
              </Badge>
            ) : null}
            {typeof entry.device_count === "number" ? (
              <span className="text-[11px] text-muted-foreground">
                {entry.device_count} device{entry.device_count === 1 ? "" : "s"}
              </span>
            ) : null}
            {entry.written_at ? (
              <span className="text-[11px] text-muted-foreground">{entry.written_at}</span>
            ) : null}
          </div>

          {entry.file_path ? (
            <p className="mb-2 break-all text-[11px] text-muted-foreground">
              File: <span className="font-mono">{entry.file_path}</span>
              {entry.append ? " (appended)" : ""}
            </p>
          ) : null}

          {entry.content ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-2 text-[11px] font-mono">
              {entry.content}
            </pre>
          ) : (
            <p className="text-xs text-muted-foreground">No attribute dump recorded.</p>
          )}
        </div>
      ))}
    </div>
  );
}

function summarizeDeviceStatuses(devices: DeviceContext[]) {
  return devices.reduce(
    (counts, device) => {
      if (device.status === "ok") {
        counts.ok += 1;
      } else if (device.status === "failed") {
        counts.failed += 1;
      } else {
        counts.other += 1;
      }
      return counts;
    },
    { ok: 0, failed: 0, other: 0 },
  );
}

function DeviceStatusSummary({ devices }: { devices: DeviceContext[] }) {
  const counts = useMemo(() => summarizeDeviceStatuses(devices), [devices]);
  const parts: string[] = [];
  if (counts.ok > 0) {
    parts.push(`${counts.ok} ok`);
  }
  if (counts.failed > 0) {
    parts.push(`${counts.failed} failed`);
  }
  if (counts.other > 0) {
    parts.push(`${counts.other} other`);
  }

  return (
    <span className="font-normal normal-case tracking-normal">
      {parts.length > 0 ? parts.join(" · ") : "no status recorded"}
    </span>
  );
}

function DevicesSection({
  devices,
  runId,
  compact = false,
}: {
  devices: DeviceContext[];
  runId?: number | null;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(
    () => !compact && devices.length <= DEVICES_COLLAPSE_THRESHOLD,
  );
  const scrollDeviceList = devices.length > DEVICES_COLLAPSE_THRESHOLD;

  return (
    <div className="min-w-0">
      <button
        type="button"
        className="mb-2 flex w-full min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="size-3.5 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="size-3.5 shrink-0" aria-hidden />
        )}
        <Server className="size-3.5 shrink-0" aria-hidden />
        <span>Devices ({devices.length})</span>
        {!expanded && devices.length > 0 ? (
          <>
            <span className="font-normal normal-case tracking-normal text-muted-foreground/70">
              —
            </span>
            <DeviceStatusSummary devices={devices} />
          </>
        ) : null}
      </button>

      {devices.length === 0 ? (
        <p className="text-xs text-muted-foreground">No devices on this outcome path.</p>
      ) : expanded ? (
        <div
          className={cn(
            "min-w-0 space-y-2",
            scrollDeviceList && "max-h-96 overflow-y-auto pr-1",
          )}
        >
          {devices.map((device) => (
            <DeviceCard key={device.id} device={device} runId={runId} />
          ))}
        </div>
      ) : null}
    </div>
  );
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
      <p className="text-muted-foreground">
        {artifactRef.kind}
        {artifactRef.size_bytes != null ? ` · ${artifactRef.size_bytes} bytes` : ""}
      </p>
    </div>
  );
}

interface ParsedTemplateEntry {
  artifact_ref: ArtifactRef;
  step_node_id: string;
  output_key: string;
  size_bytes: number;
  kind: string;
}

interface ParsedComparisonResultEntry {
  kind: "comparison_result";
  matched: boolean;
  step_node_id: string;
  reference_path?: string;
  reference_location?: string;
  content_source?: string;
  diff_stats?: { additions: number; deletions: number };
  comparison_diff_key?: string;
}

interface ParsedComparisonDiffEntry {
  kind: "comparison_diff";
  matched: boolean;
  artifact_ref: ArtifactRef;
  step_node_id: string;
  reference_path?: string;
  reference_location?: string;
  content_source?: string;
  diff_stats?: { additions: number; deletions: number };
  output_key?: string;
}

function isParsedTemplateEntry(value: unknown): value is ParsedTemplateEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as ParsedTemplateEntry;
  return (
    typeof entry.artifact_ref === "object" &&
    entry.artifact_ref !== null &&
    typeof entry.artifact_ref.artifact_id === "string" &&
    typeof entry.output_key === "string"
  );
}

function getParsedTemplateEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedTemplateEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isParsedTemplateEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedTemplateEntry }));
}

function isComparisonResultEntry(value: unknown): value is ParsedComparisonResultEntry {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as ParsedComparisonResultEntry).kind === "comparison_result"
  );
}

function isComparisonDiffEntry(value: unknown): value is ParsedComparisonDiffEntry {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const entry = value as ParsedComparisonDiffEntry;
  return (
    entry.kind === "comparison_diff" &&
    typeof entry.artifact_ref === "object" &&
    entry.artifact_ref !== null &&
    typeof entry.artifact_ref.artifact_id === "string"
  );
}

function getComparisonResultEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedComparisonResultEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isComparisonResultEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedComparisonResultEntry }));
}

function getComparisonDiffEntries(
  parsed: Record<string, unknown>,
): Array<{ key: string; entry: ParsedComparisonDiffEntry }> {
  return Object.entries(parsed)
    .filter(([, value]) => isComparisonDiffEntry(value))
    .map(([key, entry]) => ({ key, entry: entry as ParsedComparisonDiffEntry }));
}

function ConfigArtifactPanel({
  runId,
  label,
  artifactRef,
}: {
  runId: number;
  label: string;
  artifactRef: ArtifactRef;
}) {
  const { data, isLoading, error } = useArtifactQuery({ runId, artifactRef });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Loading {label.toLowerCase()}…
      </div>
    );
  }

  if (error || !data) {
    return (
      <p className="text-xs text-amber-600">
        {label} unavailable — re-run the workflow to persist config content.
      </p>
    );
  }

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <pre className="max-h-60 overflow-auto break-all rounded bg-muted/40 p-2 text-[11px] font-mono whitespace-pre-wrap">
        {data.content}
      </pre>
    </div>
  );
}

function DeviceConfigsContent({
  runId,
  device,
}: {
  runId: number | null;
  device: DeviceContext;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Config content is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {device.running_config_ref ? (
        <ConfigArtifactPanel
          runId={runId}
          label="Running config"
          artifactRef={device.running_config_ref}
        />
      ) : null}
      {device.startup_config_ref ? (
        <ConfigArtifactPanel
          runId={runId}
          label="Startup config"
          artifactRef={device.startup_config_ref}
        />
      ) : null}
    </div>
  );
}

function DeviceParsedTemplatesContent({
  runId,
  parsedEntries,
}: {
  runId: number | null;
  parsedEntries: Array<{ key: string; entry: ParsedTemplateEntry }>;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Rendered template content is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {parsedEntries.map(({ key, entry }) => (
        <div key={key} className="space-y-1">
          <p className="font-mono text-[10px] text-muted-foreground">
            node: {entry.step_node_id}
          </p>
          <ConfigArtifactPanel
            runId={runId}
            label={`Rendered template (${entry.output_key})`}
            artifactRef={entry.artifact_ref}
          />
        </div>
      ))}
    </div>
  );
}

function DeviceComparisonDiffsContent({
  runId,
  comparisonResults,
  comparisonDiffs,
}: {
  runId: number | null;
  comparisonResults: Array<{ key: string; entry: ParsedComparisonResultEntry }>;
  comparisonDiffs: Array<{ key: string; entry: ParsedComparisonDiffEntry }>;
}) {
  if (comparisonResults.length === 0 && comparisonDiffs.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 space-y-3">
      {comparisonResults.map(({ key, entry }) => (
        <div key={key} className="space-y-1 rounded border bg-background/60 p-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Comparison
            </p>
            <Badge
              className="text-[10px]"
              variant={entry.matched ? "secondary" : "destructive"}
            >
              {entry.matched ? "match" : "mismatch"}
            </Badge>
            {entry.diff_stats ? (
              <span className="text-[11px] text-muted-foreground">
                +{entry.diff_stats.additions} / -{entry.diff_stats.deletions}
              </span>
            ) : null}
          </div>
          <p className="font-mono text-[10px] text-muted-foreground">key: {key}</p>
          {entry.reference_path ? (
            <p className="break-all text-[11px] text-muted-foreground">
              reference: <span className="font-mono">{entry.reference_path}</span>
            </p>
          ) : null}
          {entry.matched ? (
            <p className="text-xs text-muted-foreground">
              Source content matches the reference file.
            </p>
          ) : entry.comparison_diff_key ? (
            <p className="text-xs text-muted-foreground">
              Diff stored at{" "}
              <span className="font-mono">{entry.comparison_diff_key}</span>
            </p>
          ) : null}
        </div>
      ))}

      {comparisonDiffs.map(({ key, entry }) => (
        <div key={key} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-[10px] text-muted-foreground">key: {key}</p>
            {entry.diff_stats ? (
              <span className="text-[11px] text-muted-foreground">
                +{entry.diff_stats.additions} / -{entry.diff_stats.deletions}
              </span>
            ) : null}
          </div>
          {runId == null ? (
            <p className="text-xs text-muted-foreground">
              Diff content is available from a workflow run detail view.
            </p>
          ) : (
            <ConfigArtifactPanel
              runId={runId}
              label="Unified diff"
              artifactRef={entry.artifact_ref}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function DeviceCommandResultsContent({
  runId,
  commandResults,
}: {
  runId: number | null;
  commandResults: Record<string, CommandResult[]>;
}) {
  if (runId == null) {
    return (
      <p className="mt-1 text-xs text-muted-foreground">
        Command output is available from a workflow run detail view.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-3">
      {Object.entries(commandResults).map(([stepNodeId, results]) => (
        <div key={stepNodeId} className="space-y-2">
          <p className="font-mono text-[10px] text-muted-foreground">node: {stepNodeId}</p>
          {results.map((result) => (
            <div key={`${stepNodeId}-${result.command}-${result.executed_at}`} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono font-medium">{result.command}</span>
                <Badge
                  className="text-[10px]"
                  variant={result.success ? "secondary" : "destructive"}
                >
                  {result.success ? "success" : "failed"}
                </Badge>
                {result.summary ? (
                  <span className="text-muted-foreground">{result.summary}</span>
                ) : null}
              </div>
              {result.output_ref ? (
                <ConfigArtifactPanel
                  runId={runId}
                  label="Output"
                  artifactRef={result.output_ref}
                />
              ) : null}
            </div>
          ))}
        </div>
      ))}
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

function DeviceCard({ device, runId }: { device: DeviceContext; runId?: number | null }) {
  const [showAttributeBags, setShowAttributeBags] = useState(false);
  const [showConfigs, setShowConfigs] = useState(false);
  const [showCommands, setShowCommands] = useState(false);
  const [showParsedTemplates, setShowParsedTemplates] = useState(true);
  const attributeBags = device.attribute_bags ?? {};
  const attributeBagNames = Object.keys(attributeBags).filter(
    (bagName) => Object.keys(attributeBags[bagName] ?? {}).length > 0,
  );
  const parsedTemplateEntries = useMemo(
    () => getParsedTemplateEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const comparisonResultEntries = useMemo(
    () => getComparisonResultEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const comparisonDiffEntries = useMemo(
    () => getComparisonDiffEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const hasParsedTemplates = parsedTemplateEntries.length > 0;
  const hasComparisons =
    comparisonResultEntries.length > 0 || comparisonDiffEntries.length > 0;
  const [showComparisons, setShowComparisons] = useState(hasComparisons);
  const hasConfigs = Boolean(device.running_config_ref || device.startup_config_ref);
  const configCount =
    (device.running_config_ref ? 1 : 0) + (device.startup_config_ref ? 1 : 0);
  const commandResultCount = Object.values(device.command_results).reduce(
    (total, results) => total + results.length,
    0,
  );
  const hasCommandResults = commandResultCount > 0;

  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-lg border bg-card p-3">
      <div className="flex min-w-0 items-start gap-2">
        <DeviceStatusIcon status={device.status} />
        <div className="min-w-0 flex-1 overflow-hidden">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium break-words">{device.name}</p>
            <Badge className="font-mono text-[10px]" variant="outline">
              {device.status}
            </Badge>
            {device.source ? (
              <Badge className="text-[10px]" variant="secondary">
                {device.source}
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 break-all font-mono text-xs text-muted-foreground">{device.id}</p>
          <p className="break-words text-xs text-muted-foreground">
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
          {hasConfigs ? (
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
          {hasCommandResults ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Command results
              </p>
              <p className="text-xs text-muted-foreground">
                {commandResultCount} command{commandResultCount !== 1 ? "s" : ""} recorded
              </p>
            </div>
          ) : null}
          {hasParsedTemplates ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Rendered templates
              </p>
              {parsedTemplateEntries.map(({ key, entry }) => (
                <ArtifactRefRow
                  key={key}
                  label={entry.output_key}
                  artifactRef={entry.artifact_ref}
                />
              ))}
            </div>
          ) : null}
          {hasComparisons ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Comparisons
              </p>
              {comparisonResultEntries.map(({ key, entry }) => (
                <div key={key} className="text-xs text-muted-foreground">
                  <span className="font-mono">{key}</span>
                  {" · "}
                  {entry.matched ? "match" : "mismatch"}
                  {entry.diff_stats
                    ? ` (+${entry.diff_stats.additions}/-${entry.diff_stats.deletions})`
                    : ""}
                </div>
              ))}
            </div>
          ) : null}
          <DeviceErrorList errors={device.errors} />
          {hasConfigs ||
          hasCommandResults ||
          hasParsedTemplates ||
          hasComparisons ||
          attributeBagNames.length > 0 ? (
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              {attributeBagNames.length > 0 ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowAttributeBags((value) => !value)}
                >
                  {showAttributeBags ? "Hide" : "Show"} attribute bags (
                  {attributeBagNames.join(", ")})
                </button>
              ) : null}
              {hasConfigs ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowConfigs((value) => !value)}
                >
                  {showConfigs ? "Hide" : "Show"} configs ({configCount})
                </button>
              ) : null}
              {hasCommandResults ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowCommands((value) => !value)}
                >
                  {showCommands ? "Hide" : "Show"} command output ({commandResultCount})
                </button>
              ) : null}
              {hasParsedTemplates ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowParsedTemplates((value) => !value)}
                >
                  {showParsedTemplates ? "Hide" : "Show"} rendered template
                  {parsedTemplateEntries.length !== 1 ? "s" : ""} (
                  {parsedTemplateEntries.map(({ entry }) => entry.output_key).join(", ")})
                </button>
              ) : null}
              {hasComparisons ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowComparisons((value) => !value)}
                >
                  {showComparisons ? "Hide" : "Show"} comparison diff
                  {comparisonDiffEntries.length !== 1 ? "s" : ""}
                </button>
              ) : null}
            </div>
          ) : null}
          {showAttributeBags && attributeBagNames.length > 0 ? (
            <pre className="mt-1 max-h-40 overflow-auto break-all rounded bg-muted/40 p-2 text-[11px] font-mono whitespace-pre-wrap">
              {JSON.stringify(attributeBags, null, 2)}
            </pre>
          ) : null}
          {showConfigs && hasConfigs ? (
            <DeviceConfigsContent runId={runId ?? null} device={device} />
          ) : null}
          {showCommands && hasCommandResults ? (
            <DeviceCommandResultsContent
              runId={runId ?? null}
              commandResults={device.command_results}
            />
          ) : null}
          {showParsedTemplates && hasParsedTemplates ? (
            <DeviceParsedTemplatesContent
              runId={runId ?? null}
              parsedEntries={parsedTemplateEntries}
            />
          ) : null}
          {showComparisons && hasComparisons ? (
            <DeviceComparisonDiffsContent
              runId={runId ?? null}
              comparisonResults={comparisonResultEntries}
              comparisonDiffs={comparisonDiffEntries}
            />
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
          className="min-w-0 space-y-1 rounded border bg-background/60 px-2 py-1.5 text-xs"
        >
          <span className="block break-all font-mono text-muted-foreground">{key}</span>
          <span className="block max-h-24 overflow-auto break-all font-mono">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function OutcomeContextView({
  context,
  runId,
  compact = false,
}: {
  context: WorkflowContext;
  runId?: number | null;
  compact?: boolean;
}) {
  const devices = Object.values(context.devices);
  const pendingCommandNodes = Object.keys(context.pending_commands);
  const debugLogs = useMemo(() => extractDebugLogs(context.metadata), [context.metadata]);
  const showAttributes = useMemo(
    () => extractShowAttributes(context.metadata),
    [context.metadata],
  );
  const remainingMetadata = useMemo(
    () => metadataWithoutDebugPanels(context.metadata),
    [context.metadata],
  );

  return (
    <div className={cn("min-w-0 overflow-hidden", compact ? "space-y-2" : "space-y-4")}>
      <DevicesSection devices={devices} runId={runId} compact={compact} />

      {debugLogs.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Debug logs
          </p>
          <DebugLogsPanel logs={debugLogs} />
        </div>
      ) : null}

      {showAttributes.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Attribute dump
          </p>
          <ShowAttributesPanel entries={showAttributes} />
        </div>
      ) : null}

      {!compact ? (
        <>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Metadata
            </p>
            <MetadataPanel metadata={remainingMetadata} />
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
        </>
      ) : null}
    </div>
  );
}

export function StepResultViewer({
  output,
  errorMessage,
  compact = false,
  runId = null,
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
      className="min-w-0 w-full overflow-hidden"
    >
      <TabsList className="h-8 max-w-full flex-wrap">
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
        <TabsContent key={name} value={name} className="mt-3 min-w-0 overflow-x-hidden">
          <OutcomeContextView
            context={envelope.outcomes[name]}
            runId={runId}
            compact={compact}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}
