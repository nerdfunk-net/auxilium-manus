"use client";

import { PanelRightOpen } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DeviceContext } from "@/lib/workflow-context-types";

import { ArtifactRefRow } from "./artifact-ref-row";
import { CapabilityBadges } from "./capability-badges";
import { DeviceCommandResultsContent } from "./device-command-results-content";
import { DeviceComparisonDiffsContent } from "./device-comparison-diff-content";
import { DeviceConfigsContent } from "./device-configs-content";
import { DeviceDetailDialog } from "./device-detail-dialog";
import { DeviceErrorList } from "./device-error-list";
import { DeviceGenieConfigContent } from "./device-genie-config-content";
import { DeviceParsedCommandOutputContent } from "./device-parsed-command-output-content";
import { DeviceParsedTemplatesContent } from "./device-parsed-templates-content";
import { DeviceSnapshotContent } from "./device-snapshot-content";
import { DeviceStatusIcon } from "./devices-section";
import {
  getComparisonDiffEntries,
  getComparisonResultEntries,
  getGenieParsedConfigEntries,
  getParsedCommandOutputEntries,
  getParsedTemplateEntries,
  getSnapshotEntries,
} from "./parsed-guards";

export function DeviceCard({ device, runId }: { device: DeviceContext; runId?: number | null }) {
  const [detailOpen, setDetailOpen] = useState(false);
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
  const genieConfigEntries = useMemo(
    () => getGenieParsedConfigEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const snapshotEntries = useMemo(
    () => getSnapshotEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const parsedCommandOutputEntries = useMemo(
    () => getParsedCommandOutputEntries(device.parsed ?? {}),
    [device.parsed],
  );
  const hasParsedTemplates = parsedTemplateEntries.length > 0;
  const hasComparisons =
    comparisonResultEntries.length > 0 || comparisonDiffEntries.length > 0;
  const hasGenieConfig = genieConfigEntries.length > 0;
  const hasSnapshot = snapshotEntries.length > 0;
  const hasParsedCommandOutput = parsedCommandOutputEntries.length > 0;
  const [showComparisons, setShowComparisons] = useState(hasComparisons);
  const [showGenieConfig, setShowGenieConfig] = useState(false);
  const [showSnapshot, setShowSnapshot] = useState(false);
  const [showParsedCommandOutput, setShowParsedCommandOutput] = useState(false);
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
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="ml-auto h-7 shrink-0 gap-1.5 px-2 text-xs [&_svg]:size-3.5"
              onClick={() => setDetailOpen(true)}
            >
              <PanelRightOpen aria-hidden />
              Detailed view
            </Button>
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
          {hasGenieConfig ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Genie parsed config
              </p>
              {genieConfigEntries.map(({ key, entry }) => (
                <div key={key} className="text-xs text-muted-foreground">
                  <span className="font-mono">{key}</span>
                  {" · "}
                  {["running" in entry ? "running" : null, "startup" in entry ? "startup" : null]
                    .filter(Boolean)
                    .join(", ")}
                </div>
              ))}
            </div>
          ) : null}
          {hasParsedCommandOutput ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Parsed command output
              </p>
              {parsedCommandOutputEntries.map(({ key, entry }) => (
                <div key={key} className="text-xs text-muted-foreground">
                  <span className="font-mono">parsed.{key}</span>
                  {" · "}
                  {Object.keys(entry).length} command
                  {Object.keys(entry).length !== 1 ? "s" : ""}
                </div>
              ))}
            </div>
          ) : null}
          {hasSnapshot ? (
            <div className="mt-2 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Genie snapshot
              </p>
              {snapshotEntries.map(({ key, entry }) => {
                const featureNames = Object.keys(entry.features);
                const successCount = featureNames.filter(
                  (name) => entry.features[name].success,
                ).length;
                return (
                  <div key={key} className="text-xs text-muted-foreground">
                    <span className="font-mono">{key}</span>
                    {" · "}
                    {successCount}/{featureNames.length} feature
                    {featureNames.length !== 1 ? "s" : ""} learned
                  </div>
                );
              })}
            </div>
          ) : null}
          <DeviceErrorList errors={device.errors} />
          {hasConfigs ||
          hasCommandResults ||
          hasParsedTemplates ||
          hasComparisons ||
          hasGenieConfig ||
          hasSnapshot ||
          hasParsedCommandOutput ||
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
              {hasGenieConfig ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowGenieConfig((value) => !value)}
                >
                  {showGenieConfig ? "Hide" : "Show"} Genie parsed config
                </button>
              ) : null}
              {hasSnapshot ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowSnapshot((value) => !value)}
                >
                  {showSnapshot ? "Hide" : "Show"} Genie snapshot
                </button>
              ) : null}
              {hasParsedCommandOutput ? (
                <button
                  type="button"
                  className="text-xs text-primary hover:underline"
                  onClick={() => setShowParsedCommandOutput((value) => !value)}
                >
                  {showParsedCommandOutput ? "Hide" : "Show"} parsed command output
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
          {showGenieConfig && hasGenieConfig ? (
            <DeviceGenieConfigContent entries={genieConfigEntries} />
          ) : null}
          {showSnapshot && hasSnapshot ? (
            <DeviceSnapshotContent runId={runId ?? null} entries={snapshotEntries} />
          ) : null}
          {showParsedCommandOutput && hasParsedCommandOutput ? (
            <DeviceParsedCommandOutputContent entries={parsedCommandOutputEntries} />
          ) : null}
        </div>
      </div>
      <DeviceDetailDialog
        device={device}
        runId={runId ?? null}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </div>
  );
}
