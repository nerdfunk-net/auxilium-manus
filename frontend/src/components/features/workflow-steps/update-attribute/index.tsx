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
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import {
  buildUpdateAttributeConfig,
  DEFAULT_UPDATE_ATTRIBUTE_CONFIG,
  parseUpdateAttributeConfig,
  type UpdateAttributeMode,
  type RegexFlags,
} from "./update-attribute-config";
import { RegexProbePanel } from "./regex-probe-panel";
import { UpdateAttributeHelpPanel } from "./help-panel";

function AttributePathHelp() {
  return (
    <p className="text-[11px] leading-4 text-muted-foreground">
      Use <span className="font-mono">device.name</span> for core device fields,{" "}
      <span className="font-mono">nautobot.location.name</span> for Nautobot attributes, or{" "}
      <span className="font-mono">custom.field</span> for user-defined attribute bags.
    </p>
  );
}

function RegexFlagsFields({
  flags,
  nodeId,
  onChange,
}: {
  flags: RegexFlags;
  nodeId: string;
  onChange: (patch: Partial<RegexFlags>) => void;
}) {
  const items: Array<{ key: keyof RegexFlags; label: string; description: string }> = [
    {
      key: "case_insensitive",
      label: "case_insensitive",
      description: "Ignore letter case when matching.",
    },
    {
      key: "multiline",
      label: "multiline",
      description: "Treat start/end anchors per line.",
    },
    {
      key: "dotall",
      label: "dotall",
      description: "Let . match newline characters.",
    },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium">regex_flags</span>
        <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
          object
        </Badge>
      </div>
      <div className="space-y-2 rounded-lg border p-3">
        {items.map((item) => (
          <div key={item.key} className="flex items-start gap-2">
            <input
              id={`${item.key}-${nodeId}`}
              type="checkbox"
              checked={flags[item.key]}
              onChange={(event) => onChange({ [item.key]: event.target.checked })}
              className="mt-0.5 size-4 rounded border accent-teal-500"
            />
            <div className="space-y-0.5">
              <Label htmlFor={`${item.key}-${nodeId}`} className="font-mono text-xs font-medium">
                {item.label}
              </Label>
              <p className="text-[11px] text-muted-foreground">{item.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UpdateAttributeConfigPanel({
  config,
  onChange,
  nodeId,
}: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const parsed = useMemo(() => parseUpdateAttributeConfig(config), [config]);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (typeof config.mode !== "string") {
      onChange(buildUpdateAttributeConfig(config, DEFAULT_UPDATE_ATTRIBUTE_CONFIG));
    }
  }, [nodeId, config, onChange]);

  const handleModeChange = useCallback(
    (mode: UpdateAttributeMode) => {
      onChange(buildUpdateAttributeConfig(config, { mode }));
    },
    [config, onChange],
  );

  const handleDestinationPathChange = useCallback(
    (value: string) => {
      onChange(buildUpdateAttributeConfig(config, { destination_path: value }));
    },
    [config, onChange],
  );

  const handleFixedValueChange = useCallback(
    (value: string) => {
      onChange(buildUpdateAttributeConfig(config, { fixed_value: value }));
    },
    [config, onChange],
  );

  const handleSourcePathChange = useCallback(
    (value: string) => {
      onChange(buildUpdateAttributeConfig(config, { source_path: value }));
    },
    [config, onChange],
  );

  const handlePatternChange = useCallback(
    (value: string) => {
      onChange(buildUpdateAttributeConfig(config, { pattern: value }));
    },
    [config, onChange],
  );

  const handleDestinationTemplateChange = useCallback(
    (value: string) => {
      onChange(buildUpdateAttributeConfig(config, { destination_template: value }));
    },
    [config, onChange],
  );

  const handleRegexFlagsChange = useCallback(
    (patch: Partial<RegexFlags>) => {
      onChange(
        buildUpdateAttributeConfig(config, {
          regex_flags: {
            ...parsed.regex_flags,
            ...patch,
          },
        }),
      );
    },
    [config, onChange, parsed.regex_flags],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parsed.mode} onValueChange={(value) => handleModeChange(value as UpdateAttributeMode)}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Select mode" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="fixed">Fixed value</SelectItem>
            <SelectItem value="regex">Regular expression</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Fixed value writes a literal to the destination path. Regular expression reads a
          source attribute, matches a pattern, and writes an expanded destination value.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">destination_path</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={parsed.destination_path}
          onChange={(event) => handleDestinationPathChange(event.target.value)}
          placeholder="custom.location"
          className="h-8 font-mono text-xs"
        />
        <AttributePathHelp />
      </div>

      {parsed.mode === "fixed" ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">fixed_value</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Input
            value={parsed.fixed_value}
            onChange={(event) => handleFixedValueChange(event.target.value)}
            placeholder="office-a"
            className="h-8 font-mono text-xs"
          />
          <p className="text-[11px] leading-4 text-muted-foreground">
            The value is written to the destination path, creating or overwriting the attribute
            in the workflow context.
          </p>
        </div>
      ) : (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">source_path</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsed.source_path}
              onChange={(event) => handleSourcePathChange(event.target.value)}
              placeholder="device.name"
              className="h-8 font-mono text-xs"
            />
            <AttributePathHelp />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">pattern</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsed.pattern}
              onChange={(event) => handlePatternChange(event.target.value)}
              placeholder={String.raw`^([^-]+)-`}
              className="h-8 font-mono text-xs"
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">destination_template</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsed.destination_template}
              onChange={(event) => handleDestinationTemplateChange(event.target.value)}
              placeholder={String.raw`DC-\1`}
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Use Python backrefs such as <span className="font-mono">{"\\1"}</span> or{" "}
              <span className="font-mono">{"\\g<location>"}</span> with named groups.
            </p>
          </div>

          <RegexFlagsFields
            flags={parsed.regex_flags}
            nodeId={nodeId}
            onChange={handleRegexFlagsChange}
          />
        </>
      )}
    </div>
  );
}

function UpdateAttributeProbeTabPanel({ config }: PluginConfigPanelProps) {
  const parsed = useMemo(() => parseUpdateAttributeConfig(config), [config]);

  return (
    <RegexProbePanel
      pattern={parsed.pattern}
      destinationTemplate={parsed.destination_template}
      regexFlags={parsed.regex_flags}
      sourcePath={parsed.source_path}
    />
  );
}

export const UpdateAttributePlugin = {
  ConfigPanel: UpdateAttributeConfigPanel,
  HelpPanel: UpdateAttributeHelpPanel,
  modalTabs: [
    {
      id: "probe",
      label: "Probe",
      Panel: UpdateAttributeProbeTabPanel,
      isVisible: (config: Record<string, unknown>) =>
        parseUpdateAttributeConfig(config).mode === "regex",
    },
  ],
};
