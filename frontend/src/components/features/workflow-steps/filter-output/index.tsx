"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  EMPTY_PLUGINS,
  EMPTY_WORKFLOW_EDGES,
  EMPTY_WORKFLOW_NODES,
} from "@/components/features/workflows/constants/empty-canvas";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { ContentSourcePicker } from "@/components/features/workflow-steps/shared/content-source-picker";
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/shared/upstream-source-steps";
import { findUpstreamOutput } from "@/components/features/workflows/utils/upstream-output";

import { FilterRulesFields, type FilterRule } from "./filter-rules-fields";
import { FilterOutputHelpPanel } from "./help-panel";

type RuleType = "pattern" | "path";

const EMPTY_RULES: FilterRule[] = [];

// filter-output only accepts raw command/merged output, not the full shared
// master list — a distinct, hand-written set with copy specific to this step.
const FILTER_OUTPUT_SOURCE_OPTIONS = [
  {
    value: "upstream_output",
    label: "Upstream output (auto-detected)",
    hint: "Automatically resolved from the nearest content-producing upstream step.",
  },
  {
    value: "command_output",
    label: "Command output",
    hint: "Read output from a specific run-command step.",
  },
  {
    value: "merged_content",
    label: "Merged content",
    hint: "Read output from a merge-content step.",
  },
] as const;

const VALID_FILTER_SOURCES = new Set(["command_output", "merged_content"]);

type ContentSource = (typeof FILTER_OUTPUT_SOURCE_OPTIONS)[number]["value"];

function rawToRules(raw: unknown): FilterRule[] {
  if (!Array.isArray(raw)) return EMPTY_RULES;
  return raw.map((item): FilterRule => {
    if (typeof item !== "object" || !item) return { type: "pattern", value: "" };
    const r = item as Record<string, unknown>;
    if (typeof r.pattern === "string") return { type: "pattern", value: r.pattern };
    if (typeof r.path === "string") return { type: "path", value: r.path };
    return { type: "pattern", value: "" };
  });
}

function rulesToRaw(rules: FilterRule[]): Record<string, string>[] {
  return rules.map((r) => ({ [r.type]: r.value }));
}

function buildConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    content_source:
      typeof config.content_source === "string" ? config.content_source : "command_output",
    source_step_node_id:
      typeof config.source_step_node_id === "string" ? config.source_step_node_id : "",
    source_command:
      typeof config.source_command === "string" ? config.source_command : "",
    filter_rules: Array.isArray(config.filter_rules) ? config.filter_rules : [],
    ...patch,
  };
}

function FilterOutputConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = EMPTY_WORKFLOW_NODES,
  workflowEdges = EMPTY_WORKFLOW_EDGES,
  plugins = EMPTY_PLUGINS,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  const upstream = useMemo(
    () =>
      workflowEdges.length > 0 && plugins.length > 0
        ? findUpstreamOutput(nodeId, workflowNodes, workflowEdges, plugins)
        : null,
    [nodeId, workflowNodes, workflowEdges, plugins],
  );

  useEffect(() => {
    if (initializedForNode.current === nodeId) return;
    initializedForNode.current = nodeId;
    if (!config.content_source) {
      if (upstream && VALID_FILTER_SOURCES.has(upstream.contentSource)) {
        onChange(
          buildConfig(config, {
            content_source: upstream.contentSource,
            source_step_node_id: upstream.sourceNodeId,
          }),
        );
      } else {
        onChange(buildConfig(config));
      }
    }
  }, [nodeId, config, onChange, upstream]);

  const contentSource = (config.content_source as ContentSource) || "command_output";
  const sourceStepNodeId =
    typeof config.source_step_node_id === "string" ? config.source_step_node_id : "";
  const sourceCommand =
    typeof config.source_command === "string" ? config.source_command : "";

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, contentSource, nodeId),
    [workflowNodes, contentSource, nodeId],
  );

  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const rules = useMemo(() => rawToRules(config.filter_rules), [config.filter_rules]);

  const autoDetected = useMemo(() => {
    if (!upstream || !VALID_FILTER_SOURCES.has(upstream.contentSource)) {
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

  const handleContentSourceChange = useCallback(
    (value: string) => {
      if (value === "upstream_output") {
        if (upstream && VALID_FILTER_SOURCES.has(upstream.contentSource)) {
          onChange(
            buildConfig(config, {
              content_source: upstream.contentSource,
              source_step_node_id: upstream.sourceNodeId,
            }),
          );
        }
        return;
      }
      onChange(buildConfig(config, { content_source: value, source_step_node_id: "", source_command: "" }));
    },
    [config, onChange, upstream],
  );

  const handleSourceStepSelect = useCallback(
    (selectedNodeId: string) => {
      onChange(buildConfig(config, { source_step_node_id: selectedNodeId }));
    },
    [config, onChange],
  );

  const handleSourceStepNodeIdChange = useCallback(
    (value: string) => {
      onChange(buildConfig(config, { source_step_node_id: value }));
    },
    [config, onChange],
  );

  const handleSourceCommandChange = useCallback(
    (value: string) => {
      onChange(buildConfig(config, { source_command: value }));
    },
    [config, onChange],
  );

  useEffect(() => {
    if (sourceSteps.length !== 1 || sourceStepNodeId) return;
    handleSourceStepSelect(sourceSteps[0].nodeId);
  }, [sourceSteps, sourceStepNodeId, handleSourceStepSelect]);

  const handleRuleTypeChange = useCallback(
    (index: number, type: RuleType) => {
      const updated = rules.map((r, i) => (i === index ? { ...r, type } : r));
      onChange(buildConfig(config, { filter_rules: rulesToRaw(updated) }));
    },
    [config, onChange, rules],
  );

  const handleRuleValueChange = useCallback(
    (index: number, value: string) => {
      const updated = rules.map((r, i) => (i === index ? { ...r, value } : r));
      onChange(buildConfig(config, { filter_rules: rulesToRaw(updated) }));
    },
    [config, onChange, rules],
  );

  const handleAddRule = useCallback(() => {
    const updated = [...rules, { type: "pattern" as RuleType, value: "" }];
    onChange(buildConfig(config, { filter_rules: rulesToRaw(updated) }));
  }, [config, onChange, rules]);

  const handleRemoveRule = useCallback(
    (index: number) => {
      const updated = rules.filter((_, i) => i !== index);
      onChange(buildConfig(config, { filter_rules: rulesToRaw(updated) }));
    },
    [config, onChange, rules],
  );

  const selectedHint = useMemo(
    () => FILTER_OUTPUT_SOURCE_OPTIONS.find((o) => o.value === contentSource)?.hint,
    [contentSource],
  );

  const sourcePlaceholder =
    contentSource === "merged_content"
      ? "Choose merge-content step…"
      : "Choose run-command step…";

  const sourceEmptyMessage =
    contentSource === "merged_content"
      ? "Add a Merge Content step to this workflow first."
      : "Add a Run Command step to this workflow first.";

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        <p className="font-medium">Remove volatile fields before comparison</p>
        <p className="mt-1 text-[11px] text-step-surface-foreground">
          Applies regex patterns or dot-path selectors to clean up command output. The filtered
          result is stored and consumed by downstream steps via{" "}
          <span className="font-mono">filtered_output</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">content_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <ContentSourcePicker
          value={contentSource}
          onChange={handleContentSourceChange}
          options={FILTER_OUTPUT_SOURCE_OPTIONS}
          isOptionDisabled={(value) =>
            value === "upstream_output" &&
            !(upstream && VALID_FILTER_SOURCES.has(upstream.contentSource))
          }
        />
        {autoDetected ? (
          <p className="text-[11px] text-step-muted-foreground">
            ↑ Auto-detected from &ldquo;{autoDetected.stepTitle}&rdquo; ({autoDetected.stepKind})
          </p>
        ) : selectedHint ? (
          <p className="text-[11px] text-muted-foreground">{selectedHint}</p>
        ) : null}
      </div>

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
              <SelectValue placeholder={sourcePlaceholder} />
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
          <p className="text-[11px] text-warning-foreground">{sourceEmptyMessage}</p>
        )}
        {selectedSourceStep ? (
          <p className="text-[11px] text-muted-foreground">
            Selected <span className="font-mono">{selectedSourceStep.nodeId}</span>
          </p>
        ) : null}
        <Input
          value={sourceStepNodeId}
          onChange={(e) => handleSourceStepNodeIdChange(e.target.value)}
          placeholder="run-command-3"
          className="h-8 font-mono text-xs"
        />
      </div>

      {contentSource === "command_output" && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">source_command</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              optional
            </Badge>
          </div>
          <Input
            value={sourceCommand}
            onChange={(e) => handleSourceCommandChange(e.target.value)}
            placeholder="show ip route"
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Leave empty to use the first command output. Enter the exact command string to filter
            a specific command from a multi-command step.
          </p>
        </div>
      )}

      <FilterRulesFields
        rules={rules}
        onAddRule={handleAddRule}
        onRuleTypeChange={handleRuleTypeChange}
        onRuleValueChange={handleRuleValueChange}
        onRemoveRule={handleRemoveRule}
      />
    </div>
  );
}

export const FilterOutputPlugin: PluginUIComponent = {
  ConfigPanel: FilterOutputConfigPanel,
  HelpPanel: FilterOutputHelpPanel,
};
