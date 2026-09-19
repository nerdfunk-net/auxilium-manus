"use client";

import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { AttributePathPicker } from "@/components/features/workflow-steps/shared/attribute-path-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  DEFAULT_PRIMARY_IPV4_PRIORITY,
  PRIMARY_IPV4_STRATEGIES,
  SOURCE_FORMAT_OPTIONS,
  type AttributeGroupKey,
  type PrimaryIpv4Strategy,
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

function parseUpdatePrimaryIpv4(config: Record<string, unknown>): boolean {
  return config.update_primary_ipv4 === true;
}

function parsePrimaryIpv4Priority(config: Record<string, unknown>): PrimaryIpv4Strategy[] {
  const raw = config.primary_ipv4_priority;
  if (!Array.isArray(raw)) return DEFAULT_PRIMARY_IPV4_PRIORITY;
  const strategies = PRIMARY_IPV4_STRATEGIES.map((strategy) => strategy.key);
  const valid = raw.filter(
    (item): item is PrimaryIpv4Strategy =>
      typeof item === "string" && strategies.includes(item as PrimaryIpv4Strategy),
  );
  return valid.length === strategies.length ? valid : DEFAULT_PRIMARY_IPV4_PRIORITY;
}

function parsePrimaryIpv4CustomPattern(config: Record<string, unknown>): string {
  return typeof config.primary_ipv4_custom_pattern === "string"
    ? config.primary_ipv4_custom_pattern
    : "";
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
  const updatePrimaryIpv4 = parseUpdatePrimaryIpv4(config);
  const primaryIpv4Priority = useMemo(() => parsePrimaryIpv4Priority(config), [config]);
  const primaryIpv4CustomPattern = parsePrimaryIpv4CustomPattern(config);
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

  const handleUpdatePrimaryIpv4Change = useCallback(
    (checked: boolean) => {
      onChange({ ...config, update_primary_ipv4: checked });
    },
    [config, onChange],
  );

  const handleMovePriority = useCallback(
    (index: number, direction: -1 | 1) => {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= primaryIpv4Priority.length) {
        return;
      }
      const next = [...primaryIpv4Priority];
      [next[index], next[targetIndex]] = [next[targetIndex], next[index]];
      onChange({ ...config, primary_ipv4_priority: next });
    },
    [config, onChange, primaryIpv4Priority],
  );

  const handleCustomPatternChange = useCallback(
    (value: string) => {
      onChange({ ...config, primary_ipv4_custom_pattern: value });
    },
    [config, onChange],
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
          cisco_config_parser, Get &amp; Parse Config for genie, or Extract Facts
          for batfish.
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

      <div className="space-y-2 border-t pt-3">
        <label className="flex items-center gap-1.5 text-xs font-medium">
          <Checkbox
            checked={updatePrimaryIpv4}
            onCheckedChange={(checked) => handleUpdatePrimaryIpv4Change(checked === true)}
          />
          Update Primary IPv4 address
        </label>
        <p className="text-[11px] text-muted-foreground">
          Select which interface&apos;s address becomes the device&apos;s primary IPv4
          in Nautobot. When off, this step instead verifies the device&apos;s current
          primary IPv4 is still present in the parsed config — a device whose primary
          IPv4 disappeared from the config is routed to Failed.
        </p>

        {updatePrimaryIpv4 && !selected.includes("interfaces") && (
          <p className="text-[11px] text-warning-foreground">
            Has no effect until &quot;Add Interfaces&quot; is checked above — this
            step only reads and marks primary IPv4 on the interfaces it builds.
          </p>
        )}

        {updatePrimaryIpv4 ? (
          <div className="space-y-2 pl-1">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">primary_ipv4_priority</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string_list
              </Badge>
            </div>
            <div className="space-y-2">
              {primaryIpv4Priority.map((strategyKey, index) => {
                const strategy = PRIMARY_IPV4_STRATEGIES.find((item) => item.key === strategyKey);
                if (!strategy) return null;
                return (
                  <div
                    key={strategyKey}
                    className="flex items-start gap-1.5 rounded-lg border border-border bg-card p-2"
                  >
                    <div className="flex shrink-0 flex-col gap-0.5">
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-7"
                        onClick={() => handleMovePriority(index, -1)}
                        disabled={index === 0}
                        title="Move up (higher priority)"
                      >
                        <ArrowUp className="size-3.5" aria-hidden />
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        className="size-7"
                        onClick={() => handleMovePriority(index, 1)}
                        disabled={index === primaryIpv4Priority.length - 1}
                        title="Move down (lower priority)"
                      >
                        <ArrowDown className="size-3.5" aria-hidden />
                      </Button>
                    </div>
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
                          #{index + 1}
                        </Badge>
                        <span className="text-xs font-medium">{strategy.label}</span>
                      </div>
                      <p className="text-[11px] text-muted-foreground">{strategy.description}</p>
                      {strategyKey === "custom_interface" ? (
                        <Input
                          value={primaryIpv4CustomPattern}
                          onChange={(event) => handleCustomPatternChange(event.target.value)}
                          placeholder="^Vlan1$"
                          className="h-7 font-mono text-[11px]"
                        />
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">
              Tried top to bottom — the first strategy that matches an interface wins.
              Use the arrows to reorder. A secondary IP address on an interface is
              never selected as the primary.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export const ConfigToAttributesPlugin: PluginUIComponent = {
  ConfigPanel: ConfigToAttributesConfigPanel,
  HelpPanel: ConfigToAttributesHelpPanel,
};
