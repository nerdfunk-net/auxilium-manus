"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
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

import { ConfigToAttributesHelpPanel } from "./help-panel";
import {
  ATTRIBUTE_GROUPS,
  SOURCE_FORMAT_OPTIONS,
  type AttributeGroupKey,
  type SourceFormat,
} from "./types";

const CONFIG_SOURCE_OPTIONS = [
  { value: "running", label: "Running Config" },
  { value: "startup", label: "Startup Config" },
] as const;

type ConfigSource = (typeof CONFIG_SOURCE_OPTIONS)[number]["value"];

function parseConfigSource(config: Record<string, unknown>): ConfigSource {
  const raw = config.config_source;
  if (typeof raw !== "string") return "running";
  return CONFIG_SOURCE_OPTIONS.some((option) => option.value === raw)
    ? (raw as ConfigSource)
    : "running";
}

function parseSourceFormat(config: Record<string, unknown>): SourceFormat {
  const raw = config.source_format;
  if (typeof raw !== "string") return "cisco_config_parser";
  return SOURCE_FORMAT_OPTIONS.some((option) => option.value === raw)
    ? (raw as SourceFormat)
    : "cisco_config_parser";
}

function parseParsedKey(config: Record<string, unknown>): string {
  return typeof config.parsed_key === "string" ? config.parsed_key : "";
}

/**
 * The attribute path picker returns a full dotted path (e.g.
 * "parsed.pyats_config.running"), but parsed_key is just the segment right
 * after the fixed "parsed." namespace — the output_key an upstream parsing
 * step used. Extract that one segment; fall back to the raw path for any
 * shape that doesn't start with "parsed." (shouldn't normally happen here).
 */
function parsedKeyFromAttributePath(path: string): string {
  const match = /^parsed\.([^.[]+)/.exec(path);
  return match ? match[1] : path;
}

function parseAttributes(config: Record<string, unknown>): AttributeGroupKey[] {
  const raw = config.attributes;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is AttributeGroupKey =>
      typeof item === "string" && ATTRIBUTE_GROUPS.some((group) => group.key === item),
  );
}

function ConfigToAttributesConfigPanel({
  config,
  onChange,
  nodeId,
  workflowNodes,
  workflowEdges,
}: PluginConfigPanelProps) {
  const sourceFormat = useMemo(() => parseSourceFormat(config), [config]);
  const configSource = useMemo(() => parseConfigSource(config), [config]);
  const parsedKey = parseParsedKey(config);
  const selected = useMemo(() => parseAttributes(config), [config]);
  const [pickerOpen, setPickerOpen] = useState(false);

  const handleSourceFormatChange = useCallback(
    (value: string) => {
      onChange({ ...config, source_format: value });
    },
    [config, onChange],
  );

  const handleSourceChange = useCallback(
    (value: string) => {
      onChange({ ...config, config_source: value });
    },
    [config, onChange],
  );

  const handleParsedKeyChange = useCallback(
    (value: string) => {
      onChange({ ...config, parsed_key: value });
    },
    [config, onChange],
  );

  const handlePickerSelect = useCallback(
    (path: string) => {
      handleParsedKeyChange(parsedKeyFromAttributePath(path));
    },
    [handleParsedKeyChange],
  );

  const handleToggle = useCallback(
    (key: AttributeGroupKey) => {
      const next = selected.includes(key)
        ? selected.filter((item) => item !== key)
        : [...selected, key];
      onChange({ ...config, attributes: next });
    },
    [config, onChange, selected],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">source_format</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Label className="sr-only" htmlFor="source-format">
          Source format
        </Label>
        <Select value={sourceFormat} onValueChange={handleSourceFormatChange}>
          <SelectTrigger id="source-format" className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOURCE_FORMAT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">config_source</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Label className="sr-only" htmlFor="config-source">
          Config source
        </Label>
        <Select value={configSource} onValueChange={handleSourceChange}>
          <SelectTrigger id="config-source" className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONFIG_SOURCE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">parsed_key</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            value={parsedKey}
            onChange={(event) => handleParsedKeyChange(event.target.value)}
            placeholder="cisco_config"
            className="h-8 font-mono text-xs"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            onClick={() => setPickerOpen(true)}
            title="Browse attributes"
          >
            <Search className="size-3.5" />
          </Button>
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Must match the matching upstream step&apos;s{" "}
          <span className="font-mono">output_key</span> — Parse Cisco Config for
          cisco_config_parser, or Get &amp; Parse Config for genie.
        </p>
        <AttributePathPicker
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelect={handlePickerSelect}
          nodeId={nodeId}
          workflowNodes={workflowNodes ?? []}
          workflowEdges={workflowEdges ?? []}
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">attributes</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string_list
          </Badge>
        </div>
        <div className="space-y-1 rounded-lg border border-border bg-card p-2">
          {ATTRIBUTE_GROUPS.map(({ key, label }) => (
            <label
              key={key}
              className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-0.5 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded accent-step focus:ring-2 focus:ring-step/40"
                checked={selected.includes(key)}
                onChange={() => handleToggle(key)}
              />
              <span className="text-xs">{label}</span>
            </label>
          ))}
        </div>
        {selected.length === 0 && (
          <p className="text-[11px] text-warning-foreground">No attributes selected</p>
        )}
      </div>
    </div>
  );
}

export const ConfigToAttributesPlugin: PluginUIComponent = {
  ConfigPanel: ConfigToAttributesConfigPanel,
  HelpPanel: ConfigToAttributesHelpPanel,
};
