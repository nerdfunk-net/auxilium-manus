"use client";

import { useCallback, useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

const DEFAULT_MESSAGE = "Device {device.name}: {device.network_driver}";

function buildWorkflowLogConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    message: typeof config.message === "string" ? config.message : "",
    ...patch,
  };
}

function WorkflowLogConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const message = typeof config.message === "string" ? config.message : "";

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!message.trim()) {
      onChange(buildWorkflowLogConfig(config, { message: DEFAULT_MESSAGE }));
    }
  }, [nodeId, message, config, onChange]);

  const handleMessageChange = useCallback(
    (value: string) => {
      onChange(buildWorkflowLogConfig(config, { message: value }));
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
          placeholder="Tacacs key {tacacs.shared_secret} successfully read from ISE"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Logged for every device in the workflow context. Use{" "}
          <span className="font-mono">{"{path.to.value}"}</span> to interpolate a
          device&apos;s resolved attribute, e.g.{" "}
          <span className="font-mono">device.network_driver</span>,{" "}
          <span className="font-mono">nautobot.location.name</span>, or{" "}
          <span className="font-mono">custom.field</span>. A path that doesn&apos;t resolve
          renders as an empty string.
        </p>
      </div>
    </div>
  );
}

export const WorkflowLogPlugin = {
  ConfigPanel: WorkflowLogConfigPanel,
};
