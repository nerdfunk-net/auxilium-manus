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
import { Switch } from "@/components/ui/switch";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { GetFromListHelpPanel } from "./help-panel";

const DEVICES_KEY = "devices";

interface FanOutConfig {
  enabled: boolean;
  mode: "per_device" | "chunked";
  chunk_size: number;
  max_concurrency: number;
}

const DEFAULT_FAN_OUT: FanOutConfig = {
  enabled: false,
  mode: "per_device",
  chunk_size: 1,
  max_concurrency: 0,
};

const DEFAULT_DEVICES = [""];

function fanOutFromConfig(config: Record<string, unknown>): FanOutConfig {
  const raw = config.fan_out;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const f = raw as Record<string, unknown>;
    return {
      enabled: Boolean(f.enabled),
      mode: f.mode === "chunked" ? "chunked" : "per_device",
      chunk_size: typeof f.chunk_size === "number" ? Math.max(1, f.chunk_size) : 1,
      max_concurrency:
        typeof f.max_concurrency === "number" ? Math.max(0, f.max_concurrency) : 0,
    };
  }
  return DEFAULT_FAN_OUT;
}

function parseDevices(config: Record<string, unknown>): string[] {
  const raw = config[DEVICES_KEY];
  if (!Array.isArray(raw) || raw.length === 0) {
    return [...DEFAULT_DEVICES];
  }
  return raw.map((item) => (typeof item === "string" ? item : ""));
}

function buildConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    devices: parseDevices(config),
    fan_out: fanOutFromConfig(config),
    ...patch,
  };
}

function configuredDeviceCount(devices: string[]): number {
  return devices.filter((device) => device.trim()).length;
}

function GetFromListConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config[DEVICES_KEY]) || config[DEVICES_KEY].length === 0) {
      onChange(buildConfig(config));
    }
  }, [nodeId, config, onChange]);

  const devices = useMemo(() => parseDevices(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const configuredCount = useMemo(() => configuredDeviceCount(devices), [devices]);

  const handleDeviceChange = useCallback(
    (index: number, value: string) => {
      const next = [...devices];
      next[index] = value;
      onChange(buildConfig(config, { devices: next }));
    },
    [config, devices, onChange],
  );

  const handleAddDevice = useCallback(() => {
    onChange(buildConfig(config, { devices: [...devices, ""] }));
  }, [config, devices, onChange]);

  const handleRemoveDevice = useCallback(
    (index: number) => {
      if (devices.length <= 1) {
        return;
      }
      const next = devices.filter((_, itemIndex) => itemIndex !== index);
      onChange(buildConfig(config, { devices: next }));
    },
    [config, devices, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange(buildConfig(config, { fan_out: { ...fanOut, ...patch } }));
    },
    [config, fanOut, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{DEVICES_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddDevice}
            title="Add device"
          >
            <Plus className="size-3.5" />
          </Button>
        </div>

        {configuredCount > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            {configuredCount} device{configuredCount === 1 ? "" : "s"} configured
          </p>
        ) : (
          <p className="text-[11px] text-amber-600">Enter at least one device name</p>
        )}

        <div className="space-y-2">
          {devices.map((device, index) => (
            <div key={`device-${index}`} className="flex items-center gap-2">
              <Input
                value={device}
                onChange={(event) => handleDeviceChange(index, event.target.value)}
                placeholder="router1.example.com"
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemoveDevice(index)}
                disabled={devices.length <= 1}
                title="Remove device"
              >
                <Minus className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-muted-foreground">
          Static device names passed to downstream steps as workflow targets.
        </p>
      </div>

      <div className="space-y-2 border-t pt-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-medium">fan_out</span>
          <Switch
            checked={fanOut.enabled}
            onCheckedChange={(checked) => handleFanOutChange({ enabled: checked })}
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Process each device (or chunk) as an independent Hatchet child workflow.
        </p>

        {fanOut.enabled && (
          <div className="space-y-2 pl-1">
            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">Mode</Label>
              <Select
                value={fanOut.mode}
                onValueChange={(value) =>
                  handleFanOutChange({ mode: value as "per_device" | "chunked" })
                }
              >
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="per_device">Per device (1 child per device)</SelectItem>
                  <SelectItem value="chunked">Chunked (N devices per child)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {fanOut.mode === "chunked" && (
              <div className="space-y-1">
                <Label className="text-[11px] text-muted-foreground">
                  Chunk size (devices per child)
                </Label>
                <Input
                  type="number"
                  min={1}
                  className="h-7 font-mono text-xs"
                  value={fanOut.chunk_size}
                  onChange={(event) =>
                    handleFanOutChange({
                      chunk_size: Math.max(1, Number(event.target.value)),
                    })
                  }
                />
              </div>
            )}

            <div className="space-y-1">
              <Label className="text-[11px] text-muted-foreground">
                Max concurrency (0 = unlimited, 1 = sequential)
              </Label>
              <Input
                type="number"
                min={0}
                className="h-7 font-mono text-xs"
                value={fanOut.max_concurrency}
                onChange={(event) =>
                  handleFanOutChange({
                    max_concurrency: Math.max(0, Number(event.target.value)),
                  })
                }
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export const GetFromListPlugin: PluginUIComponent = {
  ConfigPanel: GetFromListConfigPanel,
  HelpPanel: GetFromListHelpPanel,
};
