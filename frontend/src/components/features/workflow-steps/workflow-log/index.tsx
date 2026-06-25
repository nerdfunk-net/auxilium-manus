"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";

const DEFAULT_ATTRIBUTE_PATHS = ["device.name", "device.network_driver"];

function parseAttributePaths(config: Record<string, unknown>): string[] {
  const raw = config.attribute_paths;
  if (!Array.isArray(raw) || raw.length === 0) {
    return [...DEFAULT_ATTRIBUTE_PATHS];
  }
  return raw.map((item) => (typeof item === "string" ? item : "")).filter(Boolean);
}

function buildWorkflowLogConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    message: typeof config.message === "string" ? config.message : "",
    attribute_paths: parseAttributePaths(config),
    ...patch,
  };
}

function WorkflowLogConfigPanel({ config, onChange, nodeId }: PluginConfigPanelProps) {
  const initializedForNode = useRef<string | null>(null);
  const message = typeof config.message === "string" ? config.message : "";
  const attributePaths = useMemo(() => parseAttributePaths(config), [config]);

  useEffect(() => {
    if (initializedForNode.current === nodeId) {
      return;
    }
    initializedForNode.current = nodeId;
    if (!Array.isArray(config.attribute_paths) || config.attribute_paths.length === 0) {
      onChange(buildWorkflowLogConfig(config));
    }
  }, [nodeId, config, onChange]);

  const handleMessageChange = useCallback(
    (value: string) => {
      onChange(buildWorkflowLogConfig(config, { message: value }));
    },
    [config, onChange],
  );

  const handlePathChange = useCallback(
    (index: number, value: string) => {
      const next = [...attributePaths];
      next[index] = value;
      onChange(buildWorkflowLogConfig(config, { attribute_paths: next }));
    },
    [attributePaths, config, onChange],
  );

  const handleAddPath = useCallback(() => {
    onChange(
      buildWorkflowLogConfig(config, {
        attribute_paths: [...attributePaths, ""],
      }),
    );
  }, [attributePaths, config, onChange]);

  const handleRemovePath = useCallback(
    (index: number) => {
      if (attributePaths.length <= 1) {
        return;
      }
      const next = attributePaths.filter((_, itemIndex) => itemIndex !== index);
      onChange(buildWorkflowLogConfig(config, { attribute_paths: next }));
    },
    [attributePaths, config, onChange],
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
          placeholder="After Nautobot attributes"
          className="h-8 text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Optional label shown in run results to identify this log checkpoint.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">attribute_paths</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              string_list
            </Badge>
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-7"
            onClick={handleAddPath}
            title="Add attribute path"
          >
            <Plus className="size-3.5" />
          </Button>
        </div>

        <div className="space-y-2">
          {attributePaths.map((path, index) => (
            <div key={`attribute-path-${index}`} className="flex items-center gap-2">
              <Input
                value={path}
                onChange={(event) => handlePathChange(index, event.target.value)}
                placeholder="nautobot.role.name"
                className="h-8 font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-8 shrink-0"
                onClick={() => handleRemovePath(index)}
                disabled={attributePaths.length <= 1}
                title="Remove attribute path"
              >
                <Minus className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>

        <p className="text-[11px] leading-4 text-muted-foreground">
          Logged for every device in the workflow context. Use paths like{" "}
          <span className="font-mono">device.network_driver</span>,{" "}
          <span className="font-mono">nautobot.location.name</span>,{" "}
          <span className="font-mono">custom.field</span>, <span className="font-mono">status</span>
          , or <span className="font-mono">capabilities</span>.
        </p>
      </div>
    </div>
  );
}

export const WorkflowLogPlugin = {
  ConfigPanel: WorkflowLogConfigPanel,
};
