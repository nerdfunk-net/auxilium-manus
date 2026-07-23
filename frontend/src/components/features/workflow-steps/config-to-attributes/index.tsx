"use client";

import { useCallback, useMemo } from "react";

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

import { ConfigToAttributesHelpPanel } from "./help-panel";
import { ATTRIBUTE_GROUPS, type AttributeGroupKey } from "./types";

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

function parseParsedKey(config: Record<string, unknown>): string {
  return typeof config.parsed_key === "string" ? config.parsed_key : "";
}

function parseAttributes(config: Record<string, unknown>): AttributeGroupKey[] {
  const raw = config.attributes;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is AttributeGroupKey =>
      typeof item === "string" && ATTRIBUTE_GROUPS.some((group) => group.key === item),
  );
}

function ConfigToAttributesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const configSource = useMemo(() => parseConfigSource(config), [config]);
  const parsedKey = parseParsedKey(config);
  const selected = useMemo(() => parseAttributes(config), [config]);

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
        <Input
          value={parsedKey}
          onChange={(event) => handleParsedKeyChange(event.target.value)}
          placeholder="cisco_config"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Must match the upstream Parse Cisco Config step&apos;s{" "}
          <span className="font-mono">output_key</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">attributes</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string_list
          </Badge>
        </div>
        <div className="space-y-1 rounded-lg border border-slate-200 bg-white p-2">
          {ATTRIBUTE_GROUPS.map(({ key, label }) => (
            <label
              key={key}
              className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-0.5 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded accent-teal-500 focus:ring-2 focus:ring-teal-400/40"
                checked={selected.includes(key)}
                onChange={() => handleToggle(key)}
              />
              <span className="text-xs">{label}</span>
            </label>
          ))}
        </div>
        {selected.length === 0 && (
          <p className="text-[11px] text-amber-600">No attributes selected</p>
        )}
      </div>
    </div>
  );
}

export const ConfigToAttributesPlugin: PluginUIComponent = {
  ConfigPanel: ConfigToAttributesConfigPanel,
  HelpPanel: ConfigToAttributesHelpPanel,
};
