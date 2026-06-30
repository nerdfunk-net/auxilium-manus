"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { listUpstreamSourceSteps } from "@/components/features/workflow-steps/store-artifact/upstream-source-steps";
import {
  findUpstreamOutput,
  type UpstreamOutput,
} from "@/components/features/workflows/utils/upstream-output";

type RuleType = "pattern" | "path";

interface FilterRule {
  type: RuleType;
  value: string;
}

const EMPTY_RULES: FilterRule[] = [];

const CONTENT_SOURCE_OPTIONS = [
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

type ContentSource = (typeof CONTENT_SOURCE_OPTIONS)[number]["value"];

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
    filter_rules: Array.isArray(config.filter_rules) ? config.filter_rules : [],
    ...patch,
  };
}

function FilterOutputConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes = [],
  workflowEdges = [],
  plugins = [],
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [autoDetected, setAutoDetected] = useState<UpstreamOutput | null>(null);

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
        setAutoDetected(upstream);
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

  const sourceSteps = useMemo(
    () => listUpstreamSourceSteps(workflowNodes, contentSource, nodeId),
    [workflowNodes, contentSource, nodeId],
  );

  const selectedSourceStep = useMemo(
    () => sourceSteps.find((step) => step.nodeId === sourceStepNodeId) ?? null,
    [sourceSteps, sourceStepNodeId],
  );

  const rules = useMemo(() => rawToRules(config.filter_rules), [config.filter_rules]);

  const handleContentSourceChange = useCallback(
    (value: string) => {
      if (value === "upstream_output") {
        if (upstream && VALID_FILTER_SOURCES.has(upstream.contentSource)) {
          setAutoDetected(upstream);
          onChange(
            buildConfig(config, {
              content_source: upstream.contentSource,
              source_step_node_id: upstream.sourceNodeId,
            }),
          );
        }
        return;
      }
      setAutoDetected(null);
      onChange(buildConfig(config, { content_source: value, source_step_node_id: "" }));
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
    () => CONTENT_SOURCE_OPTIONS.find((o) => o.value === contentSource)?.hint,
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
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        <p className="font-medium">Remove volatile fields before comparison</p>
        <p className="mt-1 text-[11px] text-teal-800">
          Applies regex patterns or dot-path selectors to clean up command output.
          The filtered result is stored and consumed by downstream steps via{" "}
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
        <Select value={contentSource} onValueChange={handleContentSourceChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_SOURCE_OPTIONS.map((option) => (
              <SelectItem
                key={option.value}
                value={option.value}
                disabled={
                  option.value === "upstream_output" &&
                  !(upstream && VALID_FILTER_SOURCES.has(upstream.contentSource))
                }
              >
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {autoDetected ? (
          <p className="text-[11px] text-teal-700">
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
          <p className="text-[11px] text-amber-600">{sourceEmptyMessage}</p>
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

      <div className="space-y-2 border-t pt-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">filter_rules</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 gap-1 px-2 text-[11px]"
            onClick={handleAddRule}
          >
            <Plus className="size-3" aria-hidden />
            Add rule
          </Button>
        </div>

        {rules.length === 0 ? (
          <p className="text-[11px] text-amber-600">Add at least one filter rule.</p>
        ) : null}

        <div className="space-y-2">
          {rules.map((rule, index) => (
            <div key={index} className="flex items-center gap-1.5">
              <Select
                value={rule.type}
                onValueChange={(value) => handleRuleTypeChange(index, value as RuleType)}
              >
                <SelectTrigger className="h-7 w-[80px] shrink-0 text-[11px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pattern">pattern</SelectItem>
                  <SelectItem value="path">path</SelectItem>
                </SelectContent>
              </Select>
              <Input
                value={rule.value}
                onChange={(e) => handleRuleValueChange(index, e.target.value)}
                placeholder={rule.type === "pattern" ? "^uptime" : "route.ospf"}
                className="h-7 flex-1 font-mono text-xs"
              />
              <button
                type="button"
                onClick={() => handleRemoveRule(index)}
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label="Remove rule"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          ))}
        </div>

        <div className="rounded-lg bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
          <p className="font-medium text-foreground">Rule types</p>
          <p className="mt-1">
            <span className="font-mono">pattern</span> — regex on key names (JSON,
            recursive) or line content (text). E.g.{" "}
            <span className="font-mono">^uptime</span> removes all keys starting with
            uptime.
          </p>
          <p className="mt-1">
            <span className="font-mono">path</span> — dot-notation path to remove a
            specific nested JSON key. E.g.{" "}
            <span className="font-mono">route.ospf</span> removes{" "}
            <span className="font-mono">data.route.ospf</span>.
          </p>
        </div>
      </div>
    </div>
  );
}

export const FilterOutputPlugin: PluginUIComponent = {
  ConfigPanel: FilterOutputConfigPanel,
};
