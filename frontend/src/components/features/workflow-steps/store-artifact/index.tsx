"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { Badge } from "@/components/ui/badge";
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
    hint: "Requires source_step_node_id of a run-command step.",
  },
  {
    value: "latest_command_output",
    label: "Latest command output",
    hint: "Uses the most recent command result on the device.",
  },
] as const;

type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];

const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
  "{command.name}",
  "{run.timestamp}",
  "{run.id}",
];

function buildStoreArtifactConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    destination: "filesystem",
    output_subdirectory:
      typeof config.output_subdirectory === "string" ? config.output_subdirectory : "exports",
    content_source:
      typeof config.content_source === "string"
        ? config.content_source
        : "running_config",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    filename_template:
      typeof config.filename_template === "string"
        ? config.filename_template
        : "{device.name}_{nautobot.location.name}_{run.timestamp}.cfg",
    strict_templates: config.strict_templates !== false,
    retention_policy:
      typeof config.retention_policy === "string"
        ? config.retention_policy
        : "standard-90-days",
    ...patch,
  };
}

function StoreArtifactConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!config.content_source || !config.filename_template) {
      onChange(buildStoreArtifactConfig(config));
    }
  }, [nodeId, config, onChange]);

  const contentSource = (config.content_source as ContentSource) || "running_config";
  const needsStepNodeId = contentSource === "command_output";

  const selectedHint = useMemo(
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const handleContentSourceChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { content_source: value }));
    },
    [config, onChange],
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

  const handleOutputSubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { output_subdirectory: value }));
    },
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;

  const handleStrictTemplatesChange = useCallback(
    (checked: boolean) => {
      onChange(buildStoreArtifactConfig(config, { strict_templates: checked }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
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
            <span className="font-mono text-xs font-medium">source_step_node_id</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={
              typeof config.source_step_node_id === "string"
                ? config.source_step_node_id
                : ""
            }
            onChange={(event) => handleSourceStepNodeIdChange(event.target.value)}
            placeholder="run-command-3"
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Canvas node id of the run-command step whose output should be exported.
          </p>
        </div>
      ) : null}

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
          onChange={(event) => handleStrictTemplatesChange(event.target.checked)}
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
          Files are written under DATA_DIRECTORY/exports/&lt;workflow_id&gt;/&lt;run_id&gt;/.
        </p>
      </div>
    </div>
  );
}

export const StoreArtifactPlugin: PluginUIComponent = {
  ConfigPanel: StoreArtifactConfigPanel,
};
