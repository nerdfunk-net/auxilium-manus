"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/store-artifact/upstream-source-steps";

const CONTENT_SOURCE_OPTIONS = [
  {
    value: "running_config",
    label: "Running configuration",
    hint: "Requires an upstream get-device-configs (or similar) step.",
  },
  {
    value: "startup_config",
    label: "Startup configuration",
    hint: "Requires startup config on the device context.",
  },
  {
    value: "command_output",
    label: "Command output (specific step)",
    hint: "Choose the run-command step that produced the output.",
  },
  {
    value: "latest_command_output",
    label: "Latest command output",
    hint: "Uses the most recent command result on the device.",
  },
  {
    value: "rendered_template",
    label: "Rendered template",
    hint: "Choose the render-jinja-template step that produced the template.",
  },
  {
    value: "merged_content",
    label: "Merged content",
    hint: "Choose the merge-content step that combined multiple command outputs.",
  },
] as const;

type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];
type ReferenceLocation = "filesystem" | "git";

const REFERENCE_LOCATION_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Read from DATA_DIRECTORY/references/ (or reference_subdirectory).",
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
  "{run.id}",
];

function buildCompareDataConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    content_source:
      typeof config.content_source === "string" ? config.content_source : "running_config",
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
        : "references",
    git_source_id:
      typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "",
    repository_subdirectory:
      typeof config.repository_subdirectory === "string"
        ? config.repository_subdirectory
        : "",
    pull_before_read: config.pull_before_read === true,
    filename_template:
      typeof config.filename_template === "string"
        ? config.filename_template
        : "{device.name}.cfg",
    strict_templates: config.strict_templates !== false,
    normalize_line_endings: config.normalize_line_endings !== false,
    ignore_trailing_whitespace: config.ignore_trailing_whitespace === true,
    ...patch,
  };
}

function CompareDataConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = [],
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [gitSourceOpen, setGitSourceOpen] = useState(false);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.content_source || !config.filename_template) {
      onChange(buildCompareDataConfig(config));
    }
  }, [nodeId, config, onChange]);

  const referenceLocation = (config.reference_location as ReferenceLocation) || "filesystem";
  const isGitReference = referenceLocation === "git";
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";

  const contentSource = (config.content_source as ContentSource) || "running_config";
  const needsStepNodeId =
    contentSource === "command_output" ||
    contentSource === "rendered_template" ||
    contentSource === "merged_content";
  const needsParsedOutputKey = contentSource === "rendered_template";
  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, contentSource, nodeId),
    [workflowNodes, contentSource, nodeId],
  );
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const selectedHint = useMemo(
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const referenceHint = useMemo(
    () =>
      REFERENCE_LOCATION_OPTIONS.find((option) => option.value === referenceLocation)?.hint,
    [referenceLocation],
  );

  const handleReferenceLocationChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { reference_location: value }));
    },
    [config, onChange],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { content_source: value }));
    },
    [config, onChange],
  );

  const handleFilenameTemplateChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { filename_template: value }));
    },
    [config, onChange],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (contentSource === "rendered_template" && step?.outputKey) {
        const currentKey =
          typeof config.parsed_output_key === "string" ? config.parsed_output_key.trim() : "";
        if (!currentKey) {
          patch.parsed_output_key = step.outputKey;
        }
      }
      onChange(buildCompareDataConfig(config, patch));
    },
    [config, contentSource, onChange, sourceSteps],
  );

  useEffect(() => {
    if (!needsStepNodeId || sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [needsStepNodeId, sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleReferenceSubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { reference_subdirectory: value }));
    },
    [config, onChange],
  );

  const handleGitSourceIdChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { git_source_id: value }));
    },
    [config, onChange],
  );

  const handleRepositorySubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildCompareDataConfig(config, { repository_subdirectory: value }));
    },
    [config, onChange],
  );

  const handleBooleanChange = useCallback(
    (key: string, checked: boolean) => {
      onChange(buildCompareDataConfig(config, { [key]: checked }));
    },
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;
  const normalizeLineEndings = config.normalize_line_endings !== false;
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
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        <p className="font-medium">Compare workflow data to a reference file</p>
        <p className="mt-1 text-[11px] text-teal-800">
          Devices route to <span className="font-mono">match</span>,{" "}
          <span className="font-mono">mismatch</span>, or{" "}
          <span className="font-mono">failure</span> handles. On mismatch, the unified
          diff is stored per device at{" "}
          <span className="font-mono">{comparisonDiffKey}</span> for downstream steps.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="rounded border border-teal-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-teal-900">
            {comparisonDiffKey}
          </code>
          <button
            type="button"
            onClick={handleCopyDiffKey}
            className="text-[10px] text-teal-700 underline hover:text-teal-900"
          >
            {copied ? "Copied!" : "Copy key"}
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={contentSource} onValueChange={handleContentSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selectedHint ? (
          <p className="text-[11px] text-muted-foreground">{selectedHint}</p>
        ) : null}
      </div>

      {needsStepNodeId ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_step</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              step
            </Badge>
          </div>
          {sourceSteps.length > 0 ? (
            <Select
              value={sourceStepNodeId || undefined}
              onValueChange={handleSourceStepSelect}
            >
              <SelectTrigger className="h-8 text-xs">
                <SelectValue
                  placeholder={
                    contentSource === "rendered_template"
                      ? "Choose render step…"
                      : contentSource === "merged_content"
                        ? "Choose merge-content step…"
                        : "Choose run-command step…"
                  }
                />
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
            <p className="text-[11px] text-amber-600">
              {contentSource === "rendered_template"
                ? "Add a Render Jinja Template step to this workflow first."
                : contentSource === "merged_content"
                  ? "Add a Merge Content step to this workflow first."
                  : "Add a Run Command step to this workflow first."}
            </p>
          )}
          {selectedSourceStep ? (
            <p className="text-[11px] text-muted-foreground">
              Selected{" "}
              <span className="font-mono">{selectedSourceStep.nodeId}</span>
              {selectedSourceStep.outputKey
                ? ` · output_key ${selectedSourceStep.outputKey}`
                : ""}
            </p>
          ) : null}
          <Input
            value={sourceStepNodeId}
            onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
            placeholder="run-command-3"
            className="h-8 font-mono text-xs"
          />
        </div>
      ) : null}

      {needsParsedOutputKey ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">parsed_output_key</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={
              typeof config.parsed_output_key === "string" ? config.parsed_output_key : ""
            }
            onChange={(event) => handleParsedOutputKeyChange(event.target.value)}
            placeholder="device_config"
            className="h-8 font-mono text-xs"
          />
        </div>
      ) : null}

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
              <p className="text-[11px] text-amber-600">Not configured</p>
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
              onChange={(event) =>
                handleRepositorySubdirectoryChange(event.target.value)
              }
              placeholder="network/backups"
              className="h-8 font-mono text-xs"
            />
          </div>

          <Label className="flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={config.pull_before_read === true}
              onChange={(event) =>
                handleBooleanChange("pull_before_read", event.target.checked)
              }
              className="accent-teal-500"
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
                : "references"
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
          value={
            typeof config.filename_template === "string" ? config.filename_template : ""
          }
          onChange={(event) => handleFilenameTemplateChange(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Reference file path. Placeholders: {FILENAME_PLACEHOLDERS.join(", ")}.
        </p>
      </div>

      <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Comparison options
        </p>
        <Label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={strictTemplates}
            onChange={(event) =>
              onChange(buildCompareDataConfig(config, { strict_templates: event.target.checked }))
            }
            className="accent-teal-500"
            aria-hidden={false}
          />
          <span className="font-mono text-xs font-medium">strict_templates</span>
        </Label>
        <Label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={normalizeLineEndings}
            onChange={(event) =>
              onChange(
                buildCompareDataConfig(config, {
                  normalize_line_endings: event.target.checked,
                }),
              )
            }
            className="accent-teal-500"
            aria-hidden={false}
          />
          <span className="font-mono text-xs font-medium">normalize_line_endings</span>
        </Label>
        <Label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={config.ignore_trailing_whitespace === true}
            onChange={(event) =>
              onChange(
                buildCompareDataConfig(config, {
                  ignore_trailing_whitespace: event.target.checked,
                }),
              )
            }
            className="accent-teal-500"
            aria-hidden={false}
          />
          <span className="font-mono text-xs font-medium">ignore_trailing_whitespace</span>
        </Label>
      </div>
    </div>
  );
}

export const CompareDataPlugin: PluginUIComponent = {
  ConfigPanel: CompareDataConfigPanel,
};
