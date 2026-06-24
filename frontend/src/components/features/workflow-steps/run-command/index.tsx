"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";

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
import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";

const DEFAULT_COMMANDS = ["show version"];

function parseCommands(config: Record<string, unknown>): string[] {
  const raw = config.commands;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [...DEFAULT_COMMANDS];
  }
  return raw.map((item) => (typeof item === "string" ? item : ""));
}

function parseUseTextfsm(config: Record<string, unknown>): boolean {
  return config.use_textfsm === true;
}

function buildRunCommandConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    credential_reference:
      typeof config.credential_reference === "string" ? config.credential_reference : "",
    commands: parseCommands(config),
    use_textfsm: parseUseTextfsm(config),
    network_driver_override:
      typeof config.network_driver_override === "string"
        ? config.network_driver_override
        : "",
    ...patch,
  };
}

function RunCommandConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.commands) || config.commands.length === 0) {
      onChange(buildRunCommandConfig(config));
    }
  }, [nodeId, config, onChange]);
  const { data, isLoading } = useCredentialsQuery();
  const sshCredentials = useMemo(
    () =>
      (data?.credentials ?? []).filter(
        (credential) => credential.type === "ssh" && credential.status !== "expired",
      ),
    [data?.credentials],
  );

  const credentialReference =
    typeof config.credential_reference === "string" ? config.credential_reference : "";
  const commands = useMemo(() => parseCommands(config), [config]);
  const useTextfsm = useMemo(() => parseUseTextfsm(config), [config]);
  const networkDriverOverride =
    typeof config.network_driver_override === "string" ? config.network_driver_override : "";

  const handleCredentialChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { credential_reference: value }));
    },
    [config, onChange],
  );

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

  const handleTextfsmChange = useCallback(
    (checked: boolean) => {
      onChange(buildRunCommandConfig(config, { use_textfsm: checked }));
    },
    [config, onChange],
  );

  const handleDriverOverrideChange = useCallback(
    (value: string) => {
      onChange(buildRunCommandConfig(config, { network_driver_override: value }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">credential_reference</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            credential_ref
          </Badge>
        </div>

        {isLoading ? (
          <p className="text-[11px] text-muted-foreground">Loading credentials…</p>
        ) : sshCredentials.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            No SSH credentials in Settings → Credentials
          </p>
        ) : (
          <Select value={credentialReference} onValueChange={handleCredentialChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Select SSH credential" />
            </SelectTrigger>
            <SelectContent>
              {sshCredentials.map((credential) => (
                <SelectItem key={credential.id} value={credential.name}>
                  {credential.name} ({credential.username})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

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

      <div className="flex items-start gap-2">
        <input
          id="use-textfsm"
          type="checkbox"
          checked={useTextfsm}
          onChange={(event) => handleTextfsmChange(event.target.checked)}
          className="mt-0.5 size-4 rounded border"
        />
        <div className="space-y-0.5">
          <Label htmlFor="use-textfsm" className="font-mono text-xs font-medium">
            use_textfsm
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Parse command output with TextFSM when a template is available.
          </p>
        </div>
      </div>
    </div>
  );
}

export const RunCommandPlugin: PluginUIComponent = {
  ConfigPanel: RunCommandConfigPanel,
};
