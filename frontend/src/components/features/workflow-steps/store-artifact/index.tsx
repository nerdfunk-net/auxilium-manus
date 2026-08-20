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
import {
  CONTENT_SOURCE_OPTIONS,
  type ContentSource,
} from "@/components/features/workflow-steps/shared/content-source-options";
import { FILENAME_PLACEHOLDERS } from "@/components/features/workflow-steps/shared/filename-placeholders";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";
import { findUpstreamOutput } from "@/components/features/workflows/utils/upstream-output";

import { StoreArtifactContentFields } from "./content-fields";
import { StoreArtifactDestinationFields } from "./destination-fields";
import { StoreArtifactHelpPanel } from "./help-panel";

type Destination = "filesystem" | "git";

export function buildStoreArtifactConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    destination:
      config.destination === "git" || config.destination === "filesystem"
        ? config.destination
        : "filesystem",
    output_subdirectory:
      typeof config.output_subdirectory === "string" ? config.output_subdirectory : "exports",
    content_source:
      typeof config.content_source === "string"
        ? config.content_source
        : "running_config",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    parsed_output_key:
      typeof config.parsed_output_key === "string" ? config.parsed_output_key : "",
    filename_template:
      typeof config.filename_template === "string"
        ? config.filename_template
        : "{device.name}_{nautobot.location.name}_{run.timestamp}.cfg",
    strict_templates: config.strict_templates !== false,
    retention_policy:
      typeof config.retention_policy === "string"
        ? config.retention_policy
        : "standard-90-days",
    git_source_id:
      typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "",
    repository_subdirectory:
      typeof config.repository_subdirectory === "string"
        ? config.repository_subdirectory
        : "",
    pull_before_write: config.pull_before_write === true,
    commit_after_write: config.commit_after_write === true,
    push_after_write: config.push_after_write === true,
    commit_message_template:
      typeof config.commit_message_template === "string"
        ? config.commit_message_template
        : "commit {timestamp}",
    ...patch,
  };
}

function StoreArtifactConfigPanel({
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
    if (!config.content_source && upstream) {
      onChange(
        buildStoreArtifactConfig(config, {
          content_source: upstream.contentSource,
          source_step_node_id: upstream.sourceNodeId,
        }),
      );
    } else {
      onChange(buildStoreArtifactConfig(config));
    }
  }, [nodeId, config, onChange, upstream]);

  const destination = (config.destination as Destination) || "filesystem";
  const isGitDestination = destination === "git";
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";

  const contentSource = (config.content_source as ContentSource) || "running_config";
  const needsStepNodeId =
    contentSource === "command_output" ||
    contentSource === "rendered_template" ||
    contentSource === "merged_content" ||
    contentSource === "comparison_diff" ||
    contentSource === "filtered_output" ||
    contentSource === "pyats_snapshot" ||
    contentSource === "updated_content";
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
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const autoDetected = useMemo(() => {
    if (!upstream) {
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

  const handleDestinationChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { destination: value }));
    },
    [config, onChange],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      if (value === "upstream_output") {
        if (upstream) {
          onChange(
            buildStoreArtifactConfig(config, {
              content_source: upstream.contentSource,
              source_step_node_id: upstream.sourceNodeId,
            }),
          );
        }
        return;
      }
      onChange(buildStoreArtifactConfig(config, { content_source: value }));
    },
    [config, onChange, upstream],
  );

  const handleFilenameTemplateChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { filename_template: value }));
    },
    [config, onChange],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
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
      onChange(buildStoreArtifactConfig(config, patch));
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
      onChange(buildStoreArtifactConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const handleOutputSubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { output_subdirectory: value }));
    },
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;

  return (
    <div className="flex flex-col gap-4">
      <StoreArtifactDestinationFields
        destination={destination}
        isGitDestination={isGitDestination}
        gitSourceId={gitSourceId}
        gitSourceOpen={gitSourceOpen}
        onGitSourceOpenChange={setGitSourceOpen}
        repositorySubdirectory={
          typeof config.repository_subdirectory === "string"
            ? config.repository_subdirectory
            : ""
        }
        pullBeforeWrite={config.pull_before_write === true}
        commitAfterWrite={config.commit_after_write === true}
        pushAfterWrite={config.push_after_write === true}
        commitMessageTemplate={
          typeof config.commit_message_template === "string"
            ? config.commit_message_template
            : "commit {timestamp}"
        }
        onDestinationChange={handleDestinationChange}
        onGitDestinationChange={(patch) =>
          onChange(buildStoreArtifactConfig(config, patch))
        }
      />

      <StoreArtifactContentFields
        contentSource={contentSource}
        selectedHint={selectedHint}
        autoDetected={autoDetected}
        upstreamAvailable={Boolean(upstream)}
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
        onSourceStepNodeIdChange={handleSourceStepNodeIdChange}
        onParsedOutputKeyChange={handleParsedOutputKeyChange}
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
          onChange={(event) => handleFilenameTemplateChange(event.target.value)}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Placeholders: {FILENAME_PLACEHOLDERS.join(", ")}. Supports subdirectories,
          e.g. <span className="font-mono">./{"{nautobot.location.name}"}/{"{device.name}"}.cfg</span>.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <input
          id="strict-templates"
          type="checkbox"
          checked={strictTemplates}
          onChange={(event) =>
            onChange(buildStoreArtifactConfig(config, { strict_templates: event.target.checked }))
          }
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="strict-templates" className="font-mono text-xs font-medium">
            strict_templates
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Fail export when nautobot.* or command.* placeholders resolve empty.
          </p>
        </div>
      </div>

      {!isGitDestination ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">output_subdirectory</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Label className="sr-only" htmlFor="output-subdirectory">
            Output subdirectory
          </Label>
          <Input
            id="output-subdirectory"
            value={
              typeof config.output_subdirectory === "string"
                ? config.output_subdirectory
                : "exports"
            }
            onChange={(event) => handleOutputSubdirectoryChange(event.target.value)}
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Files are written under the default export directory (Settings → General) →
            exports/&lt;workflow_id&gt;/&lt;run_id&gt;/.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export const StoreArtifactPlugin: PluginUIComponent = {
  ConfigPanel: StoreArtifactConfigPanel,
  HelpPanel: StoreArtifactHelpPanel,
};
