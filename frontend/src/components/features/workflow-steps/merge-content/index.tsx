"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

type MergeMode = "text_sectioned" | "text_plain" | "json_merged";

const MERGE_MODE_OPTIONS: { value: MergeMode; label: string; hint: string }[] = [
  {
    value: "text_sectioned",
    label: "Sectioned text",
    hint: "Adds === {command} === headers before each command block.",
  },
  {
    value: "text_plain",
    label: "Plain text",
    hint: "Joins outputs with a separator. No command headers.",
  },
  {
    value: "json_merged",
    label: "JSON structure",
    hint: 'Produces { "show version": ..., "show interfaces": ... }. TextFSM parsed rows are used when available.',
  },
];

const DEFAULT_CONFIG = {
  source_step_node_ids: [] as string[],
  merge_mode: "text_sectioned" as MergeMode,
  section_separator: "\n",
  include_command_header: true,
};

function buildMergeContentConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    source_step_node_ids: Array.isArray(config.source_step_node_ids)
      ? config.source_step_node_ids
      : [],
    merge_mode:
      config.merge_mode === "text_sectioned" ||
      config.merge_mode === "text_plain" ||
      config.merge_mode === "json_merged"
        ? config.merge_mode
        : "text_sectioned",
    section_separator:
      typeof config.section_separator === "string"
        ? config.section_separator
        : "\n",
    include_command_header: config.include_command_header !== false,
    ...patch,
  };
}

function MergeContentConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = [],
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (initializedForNode.current === nodeId) return;
    initializedForNode.current = nodeId;
    if (!config.merge_mode) {
      onChange(buildMergeContentConfig(config));
    }
  }, [nodeId, config, onChange]);

  const mergeMode = (config.merge_mode as MergeMode) || DEFAULT_CONFIG.merge_mode;
  const sectionSeparator =
    typeof config.section_separator === "string"
      ? config.section_separator
      : DEFAULT_CONFIG.section_separator;
  const includeCommandHeader = config.include_command_header !== false;
  const sourceStepNodeIds = useMemo<string[]>(
    () =>
      Array.isArray(config.source_step_node_ids)
        ? (config.source_step_node_ids as string[])
        : [],
    [config.source_step_node_ids],
  );

  const runCommandNodes = useMemo(
    () =>
      workflowNodes.filter(
        (node) => node.id !== nodeId && node.data.kind === "run-command",
      ),
    [workflowNodes, nodeId],
  );

  const selectedHint = useMemo(
    () => MERGE_MODE_OPTIONS.find((o) => o.value === mergeMode)?.hint,
    [mergeMode],
  );

  const isTextMode = mergeMode !== "json_merged";

  const handleMergeModeChange = useCallback(
    (value: string) => {
      onChange(buildMergeContentConfig(config, { merge_mode: value }));
    },
    [config, onChange],
  );

  const handleSeparatorChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(buildMergeContentConfig(config, { section_separator: e.target.value }));
    },
    [config, onChange],
  );

  const handleIncludeHeaderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(buildMergeContentConfig(config, { include_command_header: e.target.checked }));
    },
    [config, onChange],
  );

  const handleSourceToggle = useCallback(
    (nodeId: string, checked: boolean) => {
      const next = checked
        ? [...sourceStepNodeIds, nodeId]
        : sourceStepNodeIds.filter((id) => id !== nodeId);
      onChange(buildMergeContentConfig(config, { source_step_node_ids: next }));
    },
    [config, onChange, sourceStepNodeIds],
  );

  const parsedKey = `${nodeId}.merged_content`;

  const handleCopy = useCallback(() => {
    void navigator.clipboard.writeText(parsedKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [parsedKey]);

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source_steps</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            step_list
          </Badge>
        </div>
        {runCommandNodes.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            Add one or more Run Command steps to this workflow first.
          </p>
        ) : (
          <div className="space-y-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5">
            {runCommandNodes.map((node) => {
              const checked = sourceStepNodeIds.includes(node.id);
              return (
                <label
                  key={node.id}
                  className="flex cursor-pointer items-center gap-2 py-0.5"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => handleSourceToggle(node.id, e.target.checked)}
                    className="accent-teal-500"
                    aria-hidden={false}
                  />
                  <span className="truncate text-xs">
                    {node.data.title?.trim() || node.id}
                  </span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {node.id}
                  </span>
                </label>
              );
            })}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          {sourceStepNodeIds.length === 0
            ? "All upstream run-command results will be merged."
            : `${sourceStepNodeIds.length} step${sourceStepNodeIds.length === 1 ? "" : "s"} selected.`}
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">merge_mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={mergeMode} onValueChange={handleMergeModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MERGE_MODE_OPTIONS.map((option) => (
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

      {isTextMode ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">section_separator</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={sectionSeparator}
            onChange={handleSeparatorChange}
            placeholder="\n"
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] text-muted-foreground">
            Inserted between each command output block. Use <code>\n</code> for newlines.
          </p>
        </div>
      ) : null}

      {mergeMode === "text_sectioned" ? (
        <div className="space-y-1.5">
          <Label className="flex cursor-pointer items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={includeCommandHeader}
              onChange={handleIncludeHeaderChange}
              className="accent-teal-500"
              aria-hidden={false}
            />
            <span className="font-mono text-xs font-medium">include_command_header</span>
          </Label>
          <p className="pl-5 text-[11px] text-muted-foreground">
            Prepends <code>=== show version ===</code> before each block.
          </p>
        </div>
      ) : null}

      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        <p className="font-medium">Use in Store Artifact</p>
        <p className="mt-1 text-[11px] text-teal-800">
          Set <span className="font-mono">content_source</span> to{" "}
          <span className="font-mono font-medium">Merged Content</span> and select this
          step as the source.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <code className="rounded border border-teal-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-teal-900">
            {parsedKey}
          </code>
          <button
            type="button"
            onClick={handleCopy}
            className="text-[10px] text-teal-700 underline hover:text-teal-900"
          >
            {copied ? "Copied!" : "Copy key"}
          </button>
        </div>
      </div>
    </div>
  );
}

export const MergeContentPlugin: PluginUIComponent = {
  ConfigPanel: MergeContentConfigPanel,
};
