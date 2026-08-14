"use client";

import type { ChangeEvent } from "react";
import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { ConfigureReplaceConfigHelpPanel } from "./help-panel";

const DESTINATION_FILENAME_KEY = "destination_filename";
const FILE_SYSTEM_KEY = "file_system";
const TIMEOUT_MINUTES_KEY = "timeout_minutes";
const DEFAULT_FILE_SYSTEM = "bootflash:";
const DEFAULT_TIMEOUT_MINUTES = 2;

function stringFromConfig(config: Record<string, unknown>, key: string, fallback = ""): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : fallback;
}

function numberFromConfig(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const raw = config[key];
  return typeof raw === "number" ? raw : fallback;
}

function ConfigureReplaceConfigConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const destinationFilename = stringFromConfig(config, DESTINATION_FILENAME_KEY);
  const fileSystem = stringFromConfig(config, FILE_SYSTEM_KEY, DEFAULT_FILE_SYSTEM);
  const timeoutMinutes = numberFromConfig(config, TIMEOUT_MINUTES_KEY, DEFAULT_TIMEOUT_MINUTES);

  const handleDestinationFilenameChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [DESTINATION_FILENAME_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleFileSystemChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [FILE_SYSTEM_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleTimeoutMinutesChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const value = Number(event.target.value);
      onChange({
        ...config,
        [TIMEOUT_MINUTES_KEY]: Number.isFinite(value) ? value : DEFAULT_TIMEOUT_MINUTES,
      });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        Requires an upstream <span className="font-medium">Add Testbed</span> step for
        credentials and device connection info.
      </p>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{DESTINATION_FILENAME_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={destinationFilename}
          onChange={handleDestinationFilenameChange}
          placeholder="startup-config-new.cfg"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Filename of the config file already present on the device.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{FILE_SYSTEM_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={fileSystem}
          onChange={handleFileSystemChange}
          placeholder="bootflash:"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Filesystem on the device where the file lives, e.g. bootflash: or nvram:.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{TIMEOUT_MINUTES_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={1}
          max={120}
          value={timeoutMinutes}
          onChange={handleTimeoutMinutesChange}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] text-muted-foreground">
          Minutes before the device auto-reverts if not confirmed (1-120).
        </p>
      </div>
    </div>
  );
}

export const ConfigureReplaceConfigPlugin: PluginUIComponent = {
  ConfigPanel: ConfigureReplaceConfigConfigPanel,
  HelpPanel: ConfigureReplaceConfigHelpPanel,
};
