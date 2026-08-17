"use client";

import { useCallback, useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { NotifyHelpPanel } from "./help-panel";

const DEFAULT_MESSAGE = "Could not get config from device {device.name}";
const DEFAULT_SEVERITY = "info";

const SEVERITY_OPTIONS = [
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "error", label: "Error" },
] as const;

function buildNotifyConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    message: typeof config.message === "string" ? config.message : "",
    severity: typeof config.severity === "string" ? config.severity : DEFAULT_SEVERITY,
    ...patch,
  };
}

function NotifyConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const message = typeof config.message === "string" ? config.message : "";
  const severity = typeof config.severity === "string" ? config.severity : DEFAULT_SEVERITY;

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!message.trim()) {
      onChange(buildNotifyConfig(config, { message: DEFAULT_MESSAGE, severity }));
    }
  }, [nodeId, message, severity, config, onChange]);

  const handleMessageChange = useCallback(
    (value: string) => {
      onChange(buildNotifyConfig(config, { message: value }));
    },
    [config, onChange],
  );

  const handleSeverityChange = useCallback(
    (value: string) => {
      onChange(buildNotifyConfig(config, { severity: value }));
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">message</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={message}
          onChange={(event) => handleMessageChange(event.target.value)}
          placeholder="Could not get config from device {device.name}"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Recorded for every device in the workflow context. Use{" "}
          <span className="font-mono">{"{path.to.value}"}</span> to interpolate a
          device&apos;s resolved attribute, e.g.{" "}
          <span className="font-mono">device.name</span>,{" "}
          <span className="font-mono">nautobot.location.name</span>, or{" "}
          <span className="font-mono">custom.field</span>. A path that doesn&apos;t resolve
          renders as an empty string.
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">severity</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={severity} onValueChange={handleSeverityChange}>
          <SelectTrigger className="h-8 text-xs focus:ring-step/40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEVERITY_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Severity recorded on the notification row. Shown as a badge on the dashboard
          Notifications card.
        </p>
      </div>
    </div>
  );
}

export const NotifyPlugin = {
  ConfigPanel: NotifyConfigPanel,
  HelpPanel: NotifyHelpPanel,
};
