"use client";

import { useCallback, useMemo } from "react";
import { Minus, Plus } from "lucide-react";

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
import { RunCatalystCenterCommandHelpPanel } from "./help-panel";

const DEFAULT_TIMEOUT = 300;
const MIN_TIMEOUT = 1;
const MAX_TIMEOUT = 300;
const MAX_COMMANDS = 20;
const DEFAULT_COMMANDS = ["show version"];
const DEFAULT_PARSED_OUTPUT_KEY = "parsed";

const PARSER_OPTIONS = [
  { value: "none", label: "None (raw text)" },
  { value: "textfsm", label: "TextFSM" },
] as const;

type ParserMode = (typeof PARSER_OPTIONS)[number]["value"];

function parseParserMode(config: Record<string, unknown>): ParserMode {
  return config.parser === "textfsm" ? "textfsm" : "none";
}

function parseString(config: Record<string, unknown>, key: string, fallback: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : fallback;
}

function parseCommands(config: Record<string, unknown>): string[] {
  const raw = config.commands;
  if (!Array.isArray(raw)) return DEFAULT_COMMANDS;
  const commands = raw.filter((item): item is string => typeof item === "string");
  return commands.length > 0 ? commands : DEFAULT_COMMANDS;
}

function parseTimeout(config: Record<string, unknown>): number {
  return typeof config.timeout === "number" && Number.isFinite(config.timeout)
    ? config.timeout
    : DEFAULT_TIMEOUT;
}

function RunCatalystCenterCommandConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const commands = useMemo(() => parseCommands(config), [config]);
  const timeout = useMemo(() => parseTimeout(config), [config]);
  const parserMode = useMemo(() => parseParserMode(config), [config]);
  const parsedOutputKey = parseString(config, "parsed_output_key", DEFAULT_PARSED_OUTPUT_KEY);
  const driverOverride = parseString(config, "network_driver_override", "");

  const handleCommandChange = useCallback(
    (index: number, value: string) => {
      const next = commands.map((command, i) => (i === index ? value : command));
      onChange({ ...config, commands: next });
    },
    [commands, config, onChange],
  );

  const handleAddCommand = useCallback(() => {
    onChange({ ...config, commands: [...commands, ""] });
  }, [commands, config, onChange]);

  const handleRemoveCommand = useCallback(
    (index: number) => {
      onChange({
        ...config,
        commands: commands.filter((_, i) => i !== index),
      });
    },
    [commands, config, onChange],
  );

  const handleTimeoutChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const clamped = Number.isFinite(parsed)
        ? Math.min(MAX_TIMEOUT, Math.max(MIN_TIMEOUT, parsed))
        : DEFAULT_TIMEOUT;
      onChange({ ...config, timeout: clamped });
    },
    [config, onChange],
  );

  const handleParserChange = useCallback(
    (value: string) => {
      onChange({ ...config, parser: value });
    },
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange({ ...config, parsed_output_key: value });
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange({ ...config, network_driver_override: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">commands</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddCommand}
            disabled={commands.length >= MAX_COMMANDS}
            title="Add command"
          >
            <Plus className="size-3.5" />
          </Button>
        </div>
        <div className="space-y-2">
          {commands.map((command, index) => (
            <div key={`command-${index}`} className="flex items-center gap-2">
              <Input
                value={command}
                onChange={(event) => handleCommandChange(index, event.target.value)}
                placeholder="show version"
                aria-label={`Command ${index + 1}`}
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemoveCommand(index)}
                disabled={commands.length <= 1}
                title="Remove command"
              >
                <Minus className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Read-only show commands only. Devices must come from Catalyst Center.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">timeout</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            seconds
          </Badge>
        </div>
        <Input
          type="number"
          min={MIN_TIMEOUT}
          max={MAX_TIMEOUT}
          value={timeout}
          onChange={(event) => handleTimeoutChange(event.target.value)}
          aria-label="Command timeout in seconds"
          className="h-8 text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">parser</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={parserMode} onValueChange={handleParserChange}>
          <SelectTrigger className="h-8 text-xs" aria-label="Output parser">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PARSER_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {parserMode === "textfsm" ? (
        <>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">parsed_output_key</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={parsedOutputKey}
              onChange={(event) => handleParsedOutputKeyChange(event.target.value)}
              placeholder={DEFAULT_PARSED_OUTPUT_KEY}
              aria-label="Parsed output key"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Read as parsed.{parsedOutputKey || DEFAULT_PARSED_OUTPUT_KEY}.&lt;command&gt;.parsed
            </p>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs font-medium">network_driver_override</span>
              <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                string
              </Badge>
            </div>
            <Input
              value={driverOverride}
              onChange={(event) => handleDriverOverrideChange(event.target.value)}
              placeholder="cisco_xe"
              aria-label="Network driver override"
              className="h-8 font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Only needed when a device has no network driver.
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

export const RunCatalystCenterCommandPlugin: PluginUIComponent = {
  ConfigPanel: RunCatalystCenterCommandConfigPanel,
  HelpPanel: RunCatalystCenterCommandHelpPanel,
};
