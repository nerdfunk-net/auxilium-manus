"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  EMPTY_PLUGINS,
  EMPTY_WORKFLOW_EDGES,
  EMPTY_WORKFLOW_NODES,
} from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import { type ContentSource } from "@/components/features/workflow-steps/shared/content-source-options";
import { FILENAME_PLACEHOLDERS } from "@/components/features/workflow-steps/shared/filename-placeholders";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";
import { findUpstreamOutput } from "@/components/features/workflows/utils/upstream-output";

import {
  COMPARE_DATA_SOURCE_OPTIONS,
  CompareDataContentFields,
  VALID_COMPARE_SOURCES,
} from "./content-fields";
import { CompareDataHelpPanel } from "./help-panel";
import {
  CompareDataReferenceFields,
  type ReferenceLocation,
} from "./reference-fields";

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
  workflowNodes = EMPTY_WORKFLOW_NODES,
  workflowEdges = EMPTY_WORKFLOW_EDGES,
  plugins = EMPTY_PLUGINS,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [gitSourceOpen, setGitSourceOpen] = useState(false);

  const upstream = useMemo(
    () =>
      workflowEdges.length > 0 && plugins.length > 0
        ? findUpstreamOutput(nodeId, workflowNodes, workflowEdges, plugins)
        : null,
    [nodeId, workflowNodes, workflowEdges, plugins],
  );

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    const needsInit = !config.content_source || !config.filename_template;
    if (!needsInit) return;
    if (!config.content_source && upstream && VALID_COMPARE_SOURCES.has(upstream.contentSource)) {
      onChange(
        buildCompareDataConfig(config, {
          content_source: upstream.contentSource,
          source_step_node_id: upstream.sourceNodeId,
        }),
      );
    } else {
      onChange(buildCompareDataConfig(config));
    }
  }, [nodeId, config, onChange, upstream]);

  const referenceLocation = (config.reference_location as ReferenceLocation) || "filesystem";
  const isGitReference = referenceLocation === "git";
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";

  const contentSource = (config.content_source as ContentSource) || "running_config";
  const needsStepNodeId =
    contentSource === "command_output" ||
    contentSource === "rendered_template" ||
    contentSource === "merged_content" ||
    contentSource === "filtered_output" ||
    contentSource === "pyats_snapshot";
  const needsParsedOutputKey =
    contentSource === "rendered_template" || contentSource === "pyats_snapshot";
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
    () => COMPARE_DATA_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const autoDetected = useMemo(() => {
    if (!upstream || !VALID_COMPARE_SOURCES.has(upstream.contentSource)) {
      return null;
    }
    if (
      contentSource === upstream.contentSource &&
      sourceStepNodeId === upstream.sourceNodeId
    ) {
      return upstream;
    }
    return null;
  }, [upstream, contentSource, sourceStepNodeId]);

  const patchConfig = useCallback(
    (patch: Record<string, unknown>) => {
      onChange(buildCompareDataConfig(config, patch));
    },
    [config, onChange],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      if (value === "upstream_output") {
        if (upstream && VALID_COMPARE_SOURCES.has(upstream.contentSource)) {
          patchConfig({
            content_source: upstream.contentSource,
            source_step_node_id: upstream.sourceNodeId,
          });
        }
        return;
      }
      patchConfig({ content_source: value });
    },
    [patchConfig, upstream],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      const step = sourceSteps.find((candidate) => candidate.nodeId === selectedNodeId);
      const patch: Record<string, unknown> = { source_step_node_id: selectedNodeId };
      if (
        (contentSource === "rendered_template" || contentSource === "pyats_snapshot") &&
        step?.outputKey
      ) {
        const currentKey =
          typeof config.parsed_output_key === "string" ? config.parsed_output_key.trim() : "";
        if (!currentKey) {
          patch.parsed_output_key = step.outputKey;
        }
      }
      patchConfig(patch);
    },
    [config, contentSource, patchConfig, sourceSteps],
  );

  useEffect(() => {
    if (!needsStepNodeId || sourceSteps.length !== 1 || sourceStepNodeId) {
      return;
    }
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [needsStepNodeId, sourceStepNodeId, sourceSteps, handleSourceStepSelect]);

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
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Compare workflow data to a reference file</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Devices route to <span className="font-mono">match</span>,{" "}
          <span className="font-mono">mismatch</span>, or{" "}
          <span className="font-mono">failure</span> handles. On mismatch, the unified
          diff is stored per device at{" "}
          <span className="font-mono">{comparisonDiffKey}</span> for downstream steps.
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

      <CompareDataContentFields
        contentSource={contentSource}
        selectedHint={selectedHint}
        autoDetected={autoDetected}
        upstreamAvailable={Boolean(
          upstream && VALID_COMPARE_SOURCES.has(upstream.contentSource),
        )}
        needsStepNodeId={needsStepNodeId}
        needsParsedOutputKey={needsParsedOutputKey}
        sourceSteps={sourceSteps}
        sourceStepNodeId={sourceStepNodeId}
        selectedSourceStep={selectedSourceStep}
        parsedOutputKey={
          typeof config.parsed_output_key === "string" ? config.parsed_output_key : ""
        }
        onContentSourceChange={handleContentSourceChange}
        onSourceStepSelect={handleSourceStepSelect}
        onSourceStepNodeIdChange={(value) => patchConfig({ source_step_node_id: value })}
        onParsedOutputKeyChange={(value) => patchConfig({ parsed_output_key: value })}
      />

      <CompareDataReferenceFields
        referenceLocation={referenceLocation}
        isGitReference={isGitReference}
        gitSourceId={gitSourceId}
        gitSourceOpen={gitSourceOpen}
        onGitSourceOpenChange={setGitSourceOpen}
        referenceSubdirectory={
          typeof config.reference_subdirectory === "string"
            ? config.reference_subdirectory
            : "references"
        }
        repositorySubdirectory={
          typeof config.repository_subdirectory === "string"
            ? config.repository_subdirectory
            : ""
        }
        pullBeforeRead={config.pull_before_read === true}
        onReferenceLocationChange={(value) => patchConfig({ reference_location: value })}
        onReferenceSubdirectoryChange={(value) => patchConfig({ reference_subdirectory: value })}
        onGitSourceIdChange={(value) => patchConfig({ git_source_id: value })}
        onRepositorySubdirectoryChange={(value) =>
          patchConfig({ repository_subdirectory: value })
        }
        onPullBeforeReadChange={(checked) => patchConfig({ pull_before_read: checked })}
      />

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
          onChange={(event) => patchConfig({ filename_template: event.target.value })}
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
            onChange={(event) => patchConfig({ strict_templates: event.target.checked })}
            className="accent-step"
            aria-hidden={false}
          />
          <span className="font-mono text-xs font-medium">strict_templates</span>
        </Label>
        <Label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={normalizeLineEndings}
            onChange={(event) => patchConfig({ normalize_line_endings: event.target.checked })}
            className="accent-step"
            aria-hidden={false}
          />
          <span className="font-mono text-xs font-medium">normalize_line_endings</span>
        </Label>
        <Label className="flex cursor-pointer items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={config.ignore_trailing_whitespace === true}
            onChange={(event) =>
              patchConfig({ ignore_trailing_whitespace: event.target.checked })
            }
            className="accent-step"
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
  HelpPanel: CompareDataHelpPanel,
};
