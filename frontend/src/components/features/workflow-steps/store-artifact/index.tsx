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
  {
    value: "rendered_template",
    label: "Rendered template",
    hint: "Requires source_step_node_id of a render-jinja-template step.",
  },
] as const;

type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];
type Destination = "filesystem" | "git";

const DESTINATION_OPTIONS = [
  {
    value: "filesystem",
    label: "Filesystem",
    hint: "Write under DATA_DIRECTORY/exports/<workflow_id>/<run_id>/.",
  },
  {
    value: "git",
    label: "Git repository",
    hint: "Write into a git source configured under Settings → Sources.",
  },
] as const;

const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
  "{command.name}",
  "{parsed.output_key}",
  "{run.timestamp}",
  "{run.id}",
];

const COMMIT_MESSAGE_PLACEHOLDERS = ["{timestamp}", "{run.id}", "{workflow.id}"];

function buildStoreArtifactConfig(
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

  const destination = (config.destination as Destination) || "filesystem";
  const isGitDestination = destination === "git";
  const [gitSourceOpen, setGitSourceOpen] = useState(false);
  const gitSourceId =
    typeof config.git_source_id === "string" ? config.git_source_id.trim().toLowerCase() : "";

  const contentSource = (config.content_source as ContentSource) || "running_config";
  const needsStepNodeId =
    contentSource === "command_output" || contentSource === "rendered_template";
  const needsParsedOutputKey = contentSource === "rendered_template";

  const selectedHint = useMemo(
    () => CONTENT_SOURCE_OPTIONS.find((option) => option.value === contentSource)?.hint,
    [contentSource],
  );

  const destinationHint = useMemo(
    () => DESTINATION_OPTIONS.find((option) => option.value === destination)?.hint,
    [destination],
  );

  const handleDestinationChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { destination: value }));
    },
    [config, onChange],
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

  const handleGitSourceIdChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { git_source_id: value }));
    },
    [config, onChange],
  );

  const handleRepositorySubdirectoryChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { repository_subdirectory: value }));
    },
    [config, onChange],
  );

  const handleCommitMessageTemplateChange = useCallback(
    (value: string) => {
      onChange(buildStoreArtifactConfig(config, { commit_message_template: value }));
    },
    [config, onChange],
  );

  const handleBooleanChange = useCallback(
    (key: string, checked: boolean) => {
      onChange(buildStoreArtifactConfig(config, { [key]: checked }));
    },
    [config, onChange],
  );

  const strictTemplates = config.strict_templates !== false;

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={destination} onValueChange={handleDestinationChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DESTINATION_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {destinationHint ? (
          <p className="text-[11px] text-muted-foreground">{destinationHint}</p>
        ) : null}
      </div>

      {isGitDestination ? (
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
            <p className="text-[11px] text-muted-foreground">
              Uses the same git sources as get-git-devices (Settings → Sources).
            </p>
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
            <p className="text-[11px] text-muted-foreground">
              Optional prefix inside the repository before the filename template path.
            </p>
          </div>

          <div className="space-y-2 rounded-lg border bg-muted/20 p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Git sync options
            </p>
            <div className="flex items-start gap-2">
              <input
                id="pull-before-write"
                type="checkbox"
                checked={config.pull_before_write === true}
                onChange={(event) =>
                  handleBooleanChange("pull_before_write", event.target.checked)
                }
                className="mt-0.5 size-4 rounded border"
              />
              <div className="space-y-0.5">
                <Label htmlFor="pull-before-write" className="font-mono text-xs font-medium">
                  pull_before_write
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  Pull latest changes once before writing. Fails the step if pull fails.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <input
                id="commit-after-write"
                type="checkbox"
                checked={config.commit_after_write === true}
                onChange={(event) =>
                  handleBooleanChange("commit_after_write", event.target.checked)
                }
                className="mt-0.5 size-4 rounded border"
              />
              <div className="space-y-0.5">
                <Label htmlFor="commit-after-write" className="font-mono text-xs font-medium">
                  commit_after_write
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  Create one commit for all files written in this step.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <input
                id="push-after-write"
                type="checkbox"
                checked={config.push_after_write === true}
                onChange={(event) =>
                  handleBooleanChange("push_after_write", event.target.checked)
                }
                className="mt-0.5 size-4 rounded border"
              />
              <div className="space-y-0.5">
                <Label htmlFor="push-after-write" className="font-mono text-xs font-medium">
                  push_after_write
                </Label>
                <p className="text-[11px] text-muted-foreground">
                  Push after commit. Disable for batch workflows that use a separate push step.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">commit_message_template</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={
                typeof config.commit_message_template === "string"
                  ? config.commit_message_template
                  : "commit {timestamp}"
              }
              onChange={(event) =>
                handleCommitMessageTemplateChange(event.target.value)
              }
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Placeholders: {COMMIT_MESSAGE_PLACEHOLDERS.join(", ")}.
            </p>
          </div>
        </>
      ) : null}

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
            placeholder={
              contentSource === "rendered_template"
                ? "render-jinja-template-3"
                : "run-command-3"
            }
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            {contentSource === "rendered_template"
              ? "Canvas node id of the render-jinja-template step whose output should be exported."
              : "Canvas node id of the run-command step whose output should be exported."}
          </p>
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
          <p className="text-[11px] text-muted-foreground">
            Optional output_key from the render step. Leave empty to export all templates
            produced by the selected step.
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
            Files are written under DATA_DIRECTORY/exports/&lt;workflow_id&gt;/&lt;run_id&gt;/.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export const StoreArtifactPlugin: PluginUIComponent = {
  ConfigPanel: StoreArtifactConfigPanel,
};
