"use client";

import { useCallback, useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { NotifyOnErrorHelpPanel } from "./help-panel";

const DEFAULT_MESSAGE =
  "Device {device.name} failed at {error.step_id} (node {error.node_id}): {error.message}";

function buildNotifyOnErrorConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    message: typeof config.message === "string" ? config.message : "",
    ...patch,
  };
}

function NotifyOnErrorConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const message = typeof config.message === "string" ? config.message : "";

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!message.trim()) {
      onChange(buildNotifyOnErrorConfig(config, { message: DEFAULT_MESSAGE }));
    }
  }, [nodeId, message, config, onChange]);

  const handleMessageChange = useCallback(
    (value: string) => {
      onChange(buildNotifyOnErrorConfig(config, { message: value }));
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
        <Textarea
          value={message}
          onChange={(event) => handleMessageChange(event.target.value)}
          placeholder={DEFAULT_MESSAGE}
          className="min-h-20 font-mono text-xs focus-visible:ring-step/40"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Rendered once per accumulated error on each device (a device that failed
          at two different steps before reaching this node gets two rows). Use{" "}
          <span className="font-mono">{"{path.to.value}"}</span> for a device
          attribute, e.g. <span className="font-mono">device.name</span>, plus{" "}
          <span className="font-mono">error.step_id</span>,{" "}
          <span className="font-mono">error.node_id</span>,{" "}
          <span className="font-mono">error.code</span>,{" "}
          <span className="font-mono">error.message</span> for the specific error
          being reported. A path that doesn&apos;t resolve renders as an empty
          string. Severity is always <span className="font-mono">error</span>.
        </p>
      </div>
    </div>
  );
}

export const NotifyOnErrorPlugin = {
  ConfigPanel: NotifyOnErrorConfigPanel,
  HelpPanel: NotifyOnErrorHelpPanel,
};
