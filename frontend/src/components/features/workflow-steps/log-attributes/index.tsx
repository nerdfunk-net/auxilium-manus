"use client";

import { useCallback, useEffect, useRef } from "react";

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
import { Switch } from "@/components/ui/switch";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { LogAttributesHelpPanel } from "./help-panel";

const OUTPUT_DESTINATION_OPTIONS = [
  {
    value: "stdout",
    label: "STDOUT",
    hint: "Print to worker logs (visible in backend/Hatchet logs and run metadata).",
  },
  {
    value: "file",
    label: "File",
    hint: "Write under DATA_DIRECTORY/log-attributes/<workflow_id>/<run_id>/.",
  },
] as const;

const OUTPUT_FORMAT_OPTIONS = [
  {
    value: "json",
    label: "JSON",
    hint: "Full workflow context as indented JSON.",
  },
  {
    value: "pretty_text",
    label: "Pretty text",
    hint: "Human-readable sections for devices, bags, parsed data, and metadata.",
  },
] as const;

type OutputDestination = (typeof OUTPUT_DESTINATION_OPTIONS)[number]["value"];
type OutputFormat = (typeof OUTPUT_FORMAT_OPTIONS)[number]["value"];

function buildLogAttributesConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const outputDestination =
    config.output_destination === "file" || config.output_destination === "stdout"
      ? config.output_destination
      : "stdout";
  const outputFormat =
    config.output_format === "pretty_text" || config.output_format === "json"
      ? config.output_format
      : "json";

  return {
    output_destination: outputDestination,
    output_format: outputFormat,
    filename: typeof config.filename === "string" ? config.filename : "attributes.txt",
    append: config.append === true,
    show_parsed_templates: config.show_parsed_templates === true,
    ...patch,
  };
}

function LogAttributesConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const outputDestination =
    config.output_destination === "file" ? "file" : ("stdout" as OutputDestination);
  const outputFormat =
    config.output_format === "pretty_text" ? "pretty_text" : ("json" as OutputFormat);
  const filename = typeof config.filename === "string" ? config.filename : "attributes.txt";
  const append = config.append === true;
  const showParsedTemplates = config.show_parsed_templates === true;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    onChange(buildLogAttributesConfig(config));
  }, [nodeId, config, onChange]);

  const handleDestinationChange = useCallback(
    (value: string) => {
      onChange(
        buildLogAttributesConfig(config, {
          output_destination: value === "file" ? "file" : "stdout",
        }),
      );
    },
    [config, onChange],
  );

  const handleFormatChange = useCallback(
    (value: string) => {
      onChange(
        buildLogAttributesConfig(config, {
          output_format: value === "pretty_text" ? "pretty_text" : "json",
        }),
      );
    },
    [config, onChange],
  );

  const handleFilenameChange = useCallback(
    (value: string) => {
      onChange(buildLogAttributesConfig(config, { filename: value }));
    },
    [config, onChange],
  );

  const handleAppendChange = useCallback(
    (checked: boolean) => {
      onChange(buildLogAttributesConfig(config, { append: checked }));
    },
    [config, onChange],
  );

  const handleShowParsedTemplatesChange = useCallback(
    (checked: boolean) => {
      onChange(buildLogAttributesConfig(config, { show_parsed_templates: checked }));
    },
    [config, onChange],
  );

  const destinationHint =
    OUTPUT_DESTINATION_OPTIONS.find((option) => option.value === outputDestination)?.hint ?? "";
  const formatHint =
    OUTPUT_FORMAT_OPTIONS.find((option) => option.value === outputFormat)?.hint ?? "";

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        Dumps the entire workflow context: device identity, every attribute bag (Nautobot,
        Git, custom), parsed values, command metadata, errors, pending commands, and
        workflow metadata.
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_destination</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={outputDestination} onValueChange={handleDestinationChange}>
          <SelectTrigger className="h-8 text-xs focus:ring-teal-400/40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OUTPUT_DESTINATION_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} className="text-xs">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">{destinationHint}</p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">output_format</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={outputFormat} onValueChange={handleFormatChange}>
          <SelectTrigger className="h-8 text-xs focus:ring-teal-400/40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OUTPUT_FORMAT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value} className="text-xs">
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">{formatHint}</p>
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="space-y-0.5">
          <Label className="text-xs font-medium">Show parsed Templates</Label>
          <p className="text-[11px] text-muted-foreground">
            Also print the rendered output of any upstream Render Jinja
            Template step (device.parsed entries of kind
            &quot;rendered_template&quot;), instead of just its artifact
            reference. Backed by the{" "}
            <span className="font-mono">show_parsed_templates</span> field.
          </p>
        </div>
        <Switch
          checked={showParsedTemplates}
          onCheckedChange={handleShowParsedTemplatesChange}
          className="data-[state=checked]:bg-teal-500"
        />
      </div>

      {outputDestination === "file" ? (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">filename</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={filename}
              onChange={(event) => handleFilenameChange(event.target.value)}
              placeholder="workflow-attributes.json"
              className="h-8 font-mono text-xs focus-visible:ring-teal-400/40"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              Relative path inside the run directory. Parent segments are allowed.
            </p>
          </div>

          <div className="flex items-center justify-between gap-3">
            <div className="space-y-0.5">
              <Label className="font-mono text-xs font-medium">append</Label>
              <p className="text-[11px] text-muted-foreground">
                Append with a separator instead of overwriting.
              </p>
            </div>
            <Switch
              checked={append}
              onCheckedChange={handleAppendChange}
              className="data-[state=checked]:bg-teal-500"
            />
          </div>
        </>
      ) : null}
    </div>
  );
}

export const LogAttributesPlugin = {
  ConfigPanel: LogAttributesConfigPanel,
  HelpPanel: LogAttributesHelpPanel,
};
