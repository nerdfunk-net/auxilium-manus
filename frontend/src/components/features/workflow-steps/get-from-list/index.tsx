"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import { GetFromListHelpPanel } from "./help-panel";

const DEVICES_KEY = "devices";

interface DeviceEntry {
  name: string;
  ip_address: string;
}

const DEFAULT_DEVICES: DeviceEntry[] = [{ name: "", ip_address: "" }];

function parseDeviceEntries(config: Record<string, unknown>): DeviceEntry[] {
  const raw = config[DEVICES_KEY];
  if (!Array.isArray(raw) || raw.length === 0) {
    return DEFAULT_DEVICES.map((entry) => ({ ...entry }));
  }
  return raw.map((item) => {
    if (typeof item === "string") {
      return { name: item, ip_address: "" };
    }
    if (item && typeof item === "object") {
      const record = item as Record<string, unknown>;
      return {
        name: typeof record.name === "string" ? record.name : "",
        ip_address: typeof record.ip_address === "string" ? record.ip_address : "",
      };
    }
    return { name: "", ip_address: "" };
  });
}

function buildConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    devices: parseDeviceEntries(config),
    fan_out: fanOutFromConfig(config),
    ...patch,
  };
}

function configuredDeviceCount(devices: DeviceEntry[]): number {
  return devices.filter((device) => device.name.trim() || device.ip_address.trim()).length;
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

  const devices = useMemo(() => parseDeviceEntries(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);
  const configuredCount = useMemo(() => configuredDeviceCount(devices), [devices]);

  const handleDeviceChange = useCallback(
    (index: number, field: keyof DeviceEntry, value: string) => {
      const next = devices.map((device, itemIndex) =>
        itemIndex === index ? { ...device, [field]: value } : device,
      );
      onChange(buildConfig(config, { devices: next }));
    },
    [config, devices, onChange],
  );

  const handleAddDevice = useCallback(() => {
    onChange(buildConfig(config, { devices: [...devices, { name: "", ip_address: "" }] }));
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
              object_list
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
          <p className="text-[11px] text-amber-600">Enter a name and/or IP address for at least one device</p>
        )}

        <div className="space-y-2">
          {devices.map((device, index) => (
            <div key={`device-${index}`} className="flex items-center gap-2">
              <Input
                value={device.name}
                onChange={(event) => handleDeviceChange(index, "name", event.target.value)}
                placeholder="router1.example.com"
                className="h-8 font-mono text-xs"
              />
              <Input
                value={device.ip_address}
                onChange={(event) => handleDeviceChange(index, "ip_address", event.target.value)}
                placeholder="10.0.0.5"
                className="h-8 w-32 shrink-0 font-mono text-xs"
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
          Static devices passed to downstream steps as workflow targets. When an
          IP address is set it is used to connect; otherwise the name is used
          as the hostname.
        </p>
      </div>

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />
    </div>
  );
}

export const GetFromListPlugin: PluginUIComponent = {
  ConfigPanel: GetFromListConfigPanel,
  HelpPanel: GetFromListHelpPanel,
};
