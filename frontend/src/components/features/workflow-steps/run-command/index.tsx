"use client";

import { Minus, Plus } from "lucide-react";
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
import { SshCredentialField } from "@/components/features/workflow-steps/shared/ssh-credential-field";
import { DeployReadTimeoutFields } from "@/components/features/workflow-steps/deploy-rendered-template/deploy-fields";
import { usePyATSSourcesQuery } from "@/hooks/queries/use-pyats-sources-query";

import { PyATSSourceSelectDialog } from "../shared/pyats-source-select-dialog";
import { pyatsSourceIdFromConfig, PYATS_SOURCE_ID_KEY } from "../shared/pyats-source-config";
import { RunCommandHelpPanel } from "./help-panel";

const DEFAULT_COMMANDS = ["show version"];
const DEFAULT_PARSED_OUTPUT_KEY = "parsed";
const DEFAULT_READ_TIMEOUT = 60;
const MIN_READ_TIMEOUT = 5;
const MAX_READ_TIMEOUT = 600;

type ParserMode = "none" | "textfsm" | "genie";

const PARSER_MODE_OPTIONS: { value: ParserMode; label: string }[] = [
  { value: "none", label: "None (raw text only)" },
  { value: "textfsm", label: "TextFSM (netmiko/ntc-templates)" },
  { value: "genie", label: "Genie (pyATS)" },
];

const EXECUTION_MODE_OPTIONS = [
  {
    value: "exec_mode",
    label: "Exec mode",
    hint: "Sends each command individually as an exec-level command (current behavior).",
  },
  {
    value: "config_mode",
    label: "Configuration mode",
    hint: "Enters configuration mode once, sends every command, then exits — like Deploy Rendered Template.",
  },
] as const;

type ExecutionMode = (typeof EXECUTION_MODE_OPTIONS)[number]["value"];

function parseCommands(config: Record<string, unknown>): string[] {
  const raw = config.commands;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [...DEFAULT_COMMANDS];
  }
  return raw.map((item) => (typeof item === "string" ? item : ""));
}

function parseParserMode(config: Record<string, unknown>): ParserMode {
  return config.parser === "textfsm" || config.parser === "genie" ? config.parser : "none";
}

function parseParsedOutputKey(config: Record<string, unknown>): string {
  return typeof config.parsed_output_key === "string" && config.parsed_output_key.trim()
    ? config.parsed_output_key
    : DEFAULT_PARSED_OUTPUT_KEY;
}

function buildRunCommandConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    credential_reference:
      typeof config.credential_reference === "string" ? config.credential_reference : "",
    credential_source: config.credential_source === "run_param" ? "run_param" : "fixed",
    credential_param:
      typeof config.credential_param === "string" ? config.credential_param : "",
    commands: parseCommands(config),
    parser: parseParserMode(config),
    network_driver_override:
      typeof config.network_driver_override === "string"
        ? config.network_driver_override
        : "",
    [PYATS_SOURCE_ID_KEY]: pyatsSourceIdFromConfig(config),
    parsed_output_key: parseParsedOutputKey(config),
    execution_mode: config.execution_mode === "config_mode" ? "config_mode" : "exec_mode",
    write_config_after_execution: config.write_config_after_execution === true,
    read_timeout:
      typeof config.read_timeout === "number" && Number.isFinite(config.read_timeout)
        ? config.read_timeout
        : DEFAULT_READ_TIMEOUT,
    auto_confirm_prompts: config.auto_confirm_prompts === true,
    ...patch,
  };

  const executionMode: ExecutionMode = merged.execution_mode === "config_mode" ? "config_mode" : "exec_mode";
  const autoConfirmPrompts = merged.auto_confirm_prompts === true;
  const parserLocked = executionMode === "config_mode" || autoConfirmPrompts;

  return {
    ...merged,
    execution_mode: executionMode,
    auto_confirm_prompts: autoConfirmPrompts,
    // parser is mutually exclusive with config_mode/auto_confirm_prompts — force it
    // back to "none" regardless of what the incoming patch tried to set it to.
    parser: parserLocked ? "none" : (merged.parser as ParserMode),
    // write_config_after_execution only applies in config_mode.
    write_config_after_execution:
      executionMode === "config_mode" ? merged.write_config_after_execution : false,
  };
}

function RunCommandConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const [sourceDialogOpen, setSourceDialogOpen] = useState(false);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.commands) || config.commands.length === 0) {
      onChange(buildRunCommandConfig(config));
    }
  }, [nodeId, config, onChange]);

  const commands = useMemo(() => parseCommands(config), [config]);
  const parserMode = useMemo(() => parseParserMode(config), [config]);
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";
  const executionMode: ExecutionMode =
    config.execution_mode === "config_mode" ? "config_mode" : "exec_mode";
  const writeConfigAfterExecution = config.write_config_after_execution === true;
  const readTimeout =
    typeof config.read_timeout === "number" && Number.isFinite(config.read_timeout)
      ? config.read_timeout
      : DEFAULT_READ_TIMEOUT;
  const autoConfirmPrompts = config.auto_confirm_prompts === true;
  const parserLocked = executionMode === "config_mode" || autoConfirmPrompts;

  const pyatsSourceId = useMemo(() => pyatsSourceIdFromConfig(config), [config]);
  const parsedOutputKey = useMemo(() => parseParsedOutputKey(config), [config]);
  const { data: pyatsSourcesData } = usePyATSSourcesQuery();
  const hasPyatsSource = (pyatsSourcesData?.sources.length ?? 0) > 0;

  // Eagerly correct a stale parser value the moment locking turns on, so a
  // workflow is never saved with e.g. parser: "textfsm" sitting under a
  // hidden section until some other field happens to be edited next.
  useEffect(() => {
    if (parserLocked && parserMode !== "none") {
      onChange(buildRunCommandConfig(config));
    }
  }, [parserLocked, parserMode, config, onChange]);

  const handleCommandChange = useCallback(
    (index: number, value: string) => {
      const next = [...commands];
      next[index] = value;
      onChange(buildRunCommandConfig(config, { commands: next }));
    },
    [commands, config, onChange],
  );

  const handleAddCommand = useCallback(() => {
    onChange(buildRunCommandConfig(config, { commands: [...commands, ""] }));
  }, [commands, config, onChange]);

  const handleRemoveCommand = useCallback(
    (index: number) => {
      if (commands.length <= 1) {
        return;
      }
      const next = commands.filter((_, itemIndex) => itemIndex !== index);
      onChange(buildRunCommandConfig(config, { commands: next }));
    },
    [commands, config, onChange],
  );

  const handleParserModeChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { parser: value }));
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { network_driver_override: value }));
    },
    [config, onChange],
  );

  const handleExecutionModeChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { execution_mode: value }));
    },
    [config, onChange],
  );

  const handleWriteConfigChange = useCallback(
    (checked: boolean) => {
      onChange(buildRunCommandConfig(config, { write_config_after_execution: checked }));
    },
    [config, onChange],
  );

  const handleReadTimeoutChange = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const clamped = Number.isFinite(parsed)
        ? Math.min(MAX_READ_TIMEOUT, Math.max(MIN_READ_TIMEOUT, parsed))
        : DEFAULT_READ_TIMEOUT;
      onChange(buildRunCommandConfig(config, { read_timeout: clamped }));
    },
    [config, onChange],
  );

  const handleAutoConfirmPromptsChange = useCallback(
    (checked: boolean) => {
      onChange(buildRunCommandConfig(config, { auto_confirm_prompts: checked }));
    },
    [config, onChange],
  );

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange(buildRunCommandConfig(config, { [PYATS_SOURCE_ID_KEY]: newSourceId }));
    },
    [config, onChange],
  );

  const handleParsedOutputKeyChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { parsed_output_key: value }));
    },
    [config, onChange],
  );

  const executionModeHint = useMemo(
    () => EXECUTION_MODE_OPTIONS.find((option) => option.value === executionMode)?.hint,
    [executionMode],
  );

  return (
    <div className="flex flex-col gap-4">
      <SshCredentialField config={config} onChange={onChange} />

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
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">execution_mode</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={executionMode} onValueChange={handleExecutionModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXECUTION_MODE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {executionModeHint ? (
          <p className="text-[11px] text-muted-foreground">{executionModeHint}</p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">network_driver_override</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={networkDriverOverride}
          onChange={(event) => handleDriverOverrideChange(event.target.value)}
          placeholder="cisco_ios (optional)"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Overrides each device&apos;s network driver for Netmiko in this step.
        </p>
      </div>

      <DeployReadTimeoutFields
        readTimeout={readTimeout}
        onReadTimeoutChange={handleReadTimeoutChange}
      />

      {executionMode === "config_mode" ? (
        <div className="flex items-start gap-2">
          <input
            id="write-config-after-execution"
            type="checkbox"
            checked={writeConfigAfterExecution}
            onChange={(event) => handleWriteConfigChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label
              htmlFor="write-config-after-execution"
              className="font-mono text-xs font-medium"
            >
              write_config_after_execution
            </Label>
            <p className="text-[11px] text-muted-foreground">
              After a successful config_mode run, run &ldquo;copy running-config
              startup-config&rdquo; and confirm the prompt automatically. Skipped when the run
              itself fails.
            </p>
          </div>
        </div>
      ) : null}

      <div className="space-y-1.5">
        <div className="flex items-start gap-2">
          <input
            id="auto-confirm-prompts"
            type="checkbox"
            checked={autoConfirmPrompts}
            onChange={(event) => handleAutoConfirmPromptsChange(event.target.checked)}
            className="mt-0.5 size-4 rounded border"
          />
          <div className="space-y-0.5">
            <Label htmlFor="auto-confirm-prompts" className="font-mono text-xs font-medium">
              auto_confirm_prompts
            </Label>
            <p className="text-[11px] text-muted-foreground">
              Automatically press Enter to accept a device&apos;s interactive confirmation (e.g.
              &ldquo;...Do you want to continue? [confirm]&rdquo;) instead of failing.
            </p>
          </div>
        </div>
        {autoConfirmPrompts ? (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            Risky: any command in this step that raises a confirmation prompt will be accepted
            automatically, with no human review. Only enable this when every command is expected
            and safe to auto-accept.
          </p>
        ) : null}
      </div>

      {parserLocked ? (
        <div className="space-y-1.5 border-t pt-3">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">parser</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Parser is unavailable when execution_mode is config_mode or auto_confirm_prompts is
            enabled.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5 border-t pt-3">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">parser</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string
            </Badge>
          </div>
          <Select value={parserMode} onValueChange={handleParserModeChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PARSER_MODE_OPTIONS.filter(
                (option) => option.value !== "genie" || hasPyatsSource,
              ).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11px] text-muted-foreground">
            Normalizes command output into structured data. Whichever parser you pick,
            downstream steps read it the same way.
          </p>

          {parserMode !== "none" && (
            <div className="space-y-2 border-t pt-3">
              {parserMode === "genie" && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-xs font-medium">{PYATS_SOURCE_ID_KEY}</span>
                    <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
                      pyats
                    </Badge>
                  </div>

                  {pyatsSourceId ? (
                    <p className="font-mono text-[11px] text-muted-foreground">
                      {pyatsSourceId}
                    </p>
                  ) : (
                    <p className="text-[11px] text-warning-foreground">Not configured</p>
                  )}

                  <Button
                    className="h-7 w-full text-xs"
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() => setSourceDialogOpen(true)}
                  >
                    {pyatsSourceId ? "Edit Source" : "Configure Source"}
                  </Button>

                  <PyATSSourceSelectDialog
                    open={sourceDialogOpen}
                    selectedSourceId={pyatsSourceId}
                    onClose={() => setSourceDialogOpen(false)}
                    onSave={handleSourceIdChange}
                  />
                </div>
              )}

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
                  placeholder="parsed"
                  className="h-8 font-mono text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  Key for this step&apos;s parsed output on each device (
                  <span className="font-mono">
                    parsed.{parsedOutputKey || "parsed"}.&quot;&lt;command&gt;&quot;
                  </span>
                  ).
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export const RunCommandPlugin: PluginUIComponent = {
  ConfigPanel: RunCommandConfigPanel,
  HelpPanel: RunCommandHelpPanel,
};
