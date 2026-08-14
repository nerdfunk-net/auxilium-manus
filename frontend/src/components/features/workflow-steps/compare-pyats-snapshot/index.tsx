"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EMPTY_WORKFLOW_NODES } from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { GitSourceSelectDialog } from "@/components/features/workflow-steps/get-git-devices/git-source-select-dialog";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";

import { ComparePyatsSnapshotHelpPanel } from "./help-panel";

type ReferenceLocation = "filesystem" | "git";

const REFERENCE_LOCATION_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Read from DATA_DIRECTORY/pyats-snapshots/ (or reference_subdirectory).",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Read from a git source configured under Settings → Sources.",
  },
] as const;

const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{git.source_file}",
  "{command.name}",
  "{parsed.output_key}",
  "{run.timestamp}",
  "{run.date}",
  "{run.id}",
];

function buildComparePyatsSnapshotConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    feature: typeof config.feature === "string" ? config.feature : "",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    reference_location:
      config.reference_location === "git" || config.reference_location === "filesystem"
        ? config.reference_location
        : "filesystem",
    reference_subdirectory:
      typeof config.reference_subdirectory === "string"
        ? config.reference_subdirectory
        : "pyats-snapshots",
    git_source_id:
      typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "",
    repository_subdirectory:
      typeof config.repository_subdirectory === "string" ? config.repository_subdirectory : "",
    pull_before_read: config.pull_before_read === true,
    filename_template:
      typeof config.filename_template === "string"
        ? config.filename_template
        : "{device.name}.pyats-snapshot.json",
    ...patch,
  };
}

function ComparePyatsSnapshotConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [gitSourceOpen, setGitSourceOpen] = useState(false);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.filename_template) {
      onChange(buildComparePyatsSnapshotConfig(config));
    }
  }, [nodeId, config, onChange]);

  const feature = typeof config.feature === "string" ? config.feature : "";
  const referenceLocation = (config.reference_location as ReferenceLocation) || "filesystem";
  const isGitReference = referenceLocation === "git";
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, "pyats_snapshot", nodeId),
    [workflowNodes, nodeId],
  );
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const referenceHint = useMemo(
    () => REFERENCE_LOCATION_OPTIONS.find((option) => option.value === referenceLocation)?.hint,
    [referenceLocation],
  );

  const handleFeatureChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { feature: value }));
    },
    [config, onChange],
  );

  const handleReferenceLocationChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { reference_location: value }));
    },
    [config, onChange],
  );

  const handleFilenameTemplateChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { filename_template: value }));
    },
    [config, onChange],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (step?.outputKey) {
        const currentKey =
          typeof config.parsed_output_key === "string" ? config.parsed_output_key.trim() : "";
        if (!currentKey) {
          patch.parsed_output_key = step.outputKey;
        }
      }
      onChange(buildComparePyatsSnapshotConfig(config, patch));
    },
    [config, onChange, sourceSteps],
  );

  useEffect(() => {
    if (sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleReferenceSubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { reference_subdirectory: value }));
    },
    [config, onChange],
  );

  const handleGitSourceIdChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { git_source_id: value }));
    },
    [config, onChange],
  );

  const handleRepositorySubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildComparePyatsSnapshotConfig(config, { repository_subdirectory: value }));
    },
    [config, onChange],
  );

  const handlePullBeforeReadChange = useCallback(
    (checked: boolean) => {
      onChange(buildComparePyatsSnapshotConfig(config, { pull_before_read: checked }));
    },
    [config, onChange],
  );

  const [copied, setCopied] = useState(false);
  const comparisonDiffKey = `${nodeId}.comparison_diff`;

  const handleCopyDiffKey = useCallback(() => {
    void navigator.clipboard.writeText(comparisonDiffKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [comparisonDiffKey]);

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Compare a live pyATS snapshot to a reference</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Devices route to <span className="font-mono">match</span>,{" "}
          <span className="font-mono">mismatch</span>, or{" "}
          <span className="font-mono">failure</span> handles. On mismatch, Genie&rsquo;s
          diff text is stored per device at <span className="font-mono">{comparisonDiffKey}</span>{" "}
          for downstream steps.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="rounded border border-step-border bg-card px-1.5 py-0.5 font-mono text-[10px] text-step-surface-foreground">
            {comparisonDiffKey}
          </code>
          <button
            type="button"
            onClick={handleCopyDiffKey}
            className="text-[10px] text-step-muted-foreground underline hover:text-step-surface-foreground"
          >
            {copied ? "Copied!" : "Copy key"}
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">feature</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={feature}
          onChange={(event) => handleFeatureChange(event.target.value)}
          placeholder="bgp"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          One Genie feature per instance; add another Compare Snapshot step to compare more.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source_step</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            step
          </Badge>
        </div>
        {sourceSteps.length > 0 ? (
          <Select value={sourceStepNodeId || undefined} onValueChange={handleSourceStepSelect}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Choose get-pyats-snapshot step…" />
            </SelectTrigger>
            <SelectContent>
              {sourceSteps.map((step) => (
                <SelectItem key={step.nodeId} value={step.nodeId}>
                  {step.title} ({step.nodeId})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <p className="text-[11px] text-warning-foreground">
            Add a Get Snapshot step to this workflow first.
          </p>
        )}
        {selectedSourceStep ? (
          <p className="text-[11px] text-muted-foreground">
            Selected <span className="font-mono">{selectedSourceStep.nodeId}</span>
            {selectedSourceStep.outputKey ? ` · output_key ${selectedSourceStep.outputKey}` : ""}
          </p>
        ) : null}
        <Input
          value={sourceStepNodeId}
          onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
          placeholder="get-pyats-snapshot-1"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">parsed_output_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            optional
          </Badge>
        </div>
        <Input
          value={typeof config.parsed_output_key === "string" ? config.parsed_output_key : ""}
          onChange={(event) => handleParsedOutputKeyChange(event.target.value)}
          placeholder="pyats_snapshot"
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1.5 border-t pt-3">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">reference_location</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={referenceLocation} onValueChange={handleReferenceLocationChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REFERENCE_LOCATION_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {referenceHint ? (
          <p className="text-[11px] text-muted-foreground">{referenceHint}</p>
        ) : null}
      </div>

      {isGitReference ? (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">git_source_id</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                git
              </Badge>
            </div>
            {gitSourceId ? (
              <p className="font-mono text-[11px] text-muted-foreground">{gitSourceId}</p>
            ) : (
              <p className="text-[11px] text-warning-foreground">Not configured</p>
            )}
            <Button
              className="h-7 w-full text-xs"
              size="sm"
              type="button"
              variant="outline"
              onClick={() => setGitSourceOpen(true)}
            >
              {gitSourceId ? "Change repository" : "Choose repository"}
            </Button>
          </div>

          <GitSourceSelectDialog
            open={gitSourceOpen}
            selectedSourceId={gitSourceId}
            onClose={() => setGitSourceOpen(false)}
            onSave={handleGitSourceIdChange}
          />

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">repository_subdirectory</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={
                typeof config.repository_subdirectory === "string"
                  ? config.repository_subdirectory
                  : ""
              }
              onChange={(event) => handleRepositorySubdirectoryChange(event.target.value)}
              placeholder="network/snapshots"
              className="h-8 font-mono text-xs"
            />
          </div>

          <Label className="flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={config.pull_before_read === true}
              onChange={(event) => handlePullBeforeReadChange(event.target.checked)}
              className="accent-step"
              aria-hidden={false}
            />
            <span className="font-mono text-xs font-medium">pull_before_read</span>
          </Label>
          <p className="pl-5 text-[11px] text-muted-foreground">
            Pull latest changes once before reading the reference file.
          </p>
        </>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">reference_subdirectory</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={
              typeof config.reference_subdirectory === "string"
                ? config.reference_subdirectory
                : "pyats-snapshots"
            }
            onChange={(event) => handleReferenceSubdirectoryChange(event.target.value)}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Files are read from DATA_DIRECTORY/&lt;reference_subdirectory&gt;/.
          </p>
        </div>
      )}

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">filename_template</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={typeof config.filename_template === "string" ? config.filename_template : ""}
          onChange={(event) => handleFilenameTemplateChange(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Reference snapshot JSON path. Placeholders: {FILENAME_PLACEHOLDERS.join(", ")}. No{" "}
          {"{feature}"} placeholder.
        </p>
      </div>
    </div>
  );
}

export const ComparePyatsSnapshotPlugin: PluginUIComponent = {
  ConfigPanel: ComparePyatsSnapshotConfigPanel,
  HelpPanel: ComparePyatsSnapshotHelpPanel,
};
