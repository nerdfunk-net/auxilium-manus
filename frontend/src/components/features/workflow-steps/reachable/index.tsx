"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

import { ReachableHelpPanel } from "./help-panel";

function parseNumber(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const value = config[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function ReachableConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const pingCount = parseNumber(config, "ping_count", 4);
  const requiredReplies = parseNumber(config, "required_replies", 1);
  const timeoutSeconds = parseNumber(config, "timeout_seconds", 2);

  const handlePingCountChange = useCallback(
    (next: number) => onChange({ ...config, ping_count: Math.max(1, Math.round(next)) }),
    [config, onChange],
  );
  const handleRequiredRepliesChange = useCallback(
    (next: number) =>
      onChange({ ...config, required_replies: Math.max(1, Math.round(next)) }),
    [config, onChange],
  );
  const handleTimeoutChange = useCallback(
    (next: number) => onChange({ ...config, timeout_seconds: Math.max(0.1, next) }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">ping_count</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={1}
          value={pingCount}
          onChange={(event) => handlePingCountChange(Number(event.target.value))}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          How many ICMP echo requests to send to each device.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">required_replies</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            integer
          </Badge>
        </div>
        <Input
          type="number"
          min={1}
          max={pingCount}
          value={requiredReplies}
          onChange={(event) => handleRequiredRepliesChange(Number(event.target.value))}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Minimum replies required for the device to be considered reachable.
          Cannot exceed <span className="font-mono">ping_count</span>.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">timeout_seconds</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            number
          </Badge>
        </div>
        <Input
          type="number"
          min={0.1}
          step={0.1}
          value={timeoutSeconds}
          onChange={(event) => handleTimeoutChange(Number(event.target.value))}
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          How long to wait for each individual ping reply, in seconds.
        </p>
      </div>
    </div>
  );
}

export const ReachablePlugin = {
  ConfigPanel: ReachableConfigPanel,
  HelpPanel: ReachableHelpPanel,
};
